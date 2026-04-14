# learning_switch.py
# SDN Learning Switch Controller using Ryu
# Dynamically learns MAC addresses and installs forwarding rules

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
import datetime

class LearningSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(LearningSwitch, self).__init__(*args, **kwargs)
        
        # THE MAC TABLE: {switch_id: {mac_address: port_number}}
        # This is the brain of the learning switch
        self.mac_to_port = {}
        
        # Stats for validation
        self.stats = {
            'packet_in_count': 0,      # how many times controller was called
            'flow_installed_count': 0,  # how many flow rules installed
            'flood_count': 0,           # how many times we had to flood
            'direct_count': 0           # how many times we knew the port
        }
        
        self.logger.info("=== SDN Learning Switch Controller Started ===")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Runs when switch connects.
        Installs the DEFAULT table-miss rule:
        'If nothing matches → send to controller'
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Empty match = matches every packet
        match = parser.OFPMatch()
        
        # Action: send to controller
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        
        # Priority 0 = lowest. Only triggers if no other rule matches.
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Switch %s connected. Table-miss rule installed.", 
                        ev.msg.datapath.id)

    def add_flow(self, datapath, priority, match, actions, 
                 idle_timeout=0, hard_timeout=0):
        """Install a flow rule into the switch."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        MAIN FUNCTION — called every time a packet has no matching rule.
        Does 4 things:
        1. Learn the source MAC address
        2. Look up the destination MAC address  
        3. Install a flow rule if destination is known
        4. Forward the packet
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        dpid = datapath.id

        # Parse the raw packet
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        # Ignore LLDP packets (network discovery protocol, not our traffic)
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst_mac = eth.dst
        src_mac = eth.src

        self.stats['packet_in_count'] += 1

        # =============================================
        # STEP 1: MAC LEARNING
        # =============================================
        # Make sure this switch has an entry in our table
        self.mac_to_port.setdefault(dpid, {})
        
        # Record: "src_mac is reachable via in_port on switch dpid"
        if src_mac not in self.mac_to_port[dpid]:
            self.mac_to_port[dpid][src_mac] = in_port
            self.logger.info(
                "[LEARNED] Switch %s: MAC %s is on port %s",
                dpid, src_mac, in_port
            )

        # =============================================
        # STEP 2: LOOK UP DESTINATION
        # =============================================
        if dst_mac in self.mac_to_port[dpid]:
            # We know exactly where to send it!
            out_port = self.mac_to_port[dpid][dst_mac]
            self.stats['direct_count'] += 1
            self.logger.info(
                "[FORWARD] %s → %s via port %s (direct)",
                src_mac, dst_mac, out_port
            )
        else:
            # Unknown destination → flood everywhere
            out_port = ofproto.OFPP_FLOOD
            self.stats['flood_count'] += 1
            self.logger.info(
                "[FLOOD] %s → %s (destination unknown)",
                src_mac, dst_mac
            )

        actions = [parser.OFPActionOutput(out_port)]

        # =============================================
        # STEP 3: INSTALL FLOW RULE (if not flooding)
        # =============================================
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst_mac,
                eth_src=src_mac
            )
            # Priority 1 — higher than table-miss (0), so this rule wins
            self.add_flow(
                datapath,
                priority=1,
                match=match,
                actions=actions,
                idle_timeout=30,   # delete if unused for 30s
                hard_timeout=120   # always delete after 2 minutes
            )
            self.stats['flow_installed_count'] += 1
            self.logger.info(
                "[FLOW INSTALLED] Switch %s: %s → port %s (idle_timeout=30)",
                dpid, dst_mac, out_port
            )

        # =============================================
        # STEP 4: FORWARD THIS CURRENT PACKET
        # =============================================
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)

        # Print summary every 10 packets
        if self.stats['packet_in_count'] % 10 == 0:
            self._print_summary(dpid)

    def _print_summary(self, dpid):
        """Print current MAC table and stats."""
        self.logger.info("\n" + "="*55)
        self.logger.info("  LEARNING SWITCH SUMMARY")
        self.logger.info("  Time: %s", 
                        datetime.datetime.now().strftime("%H:%M:%S"))
        self.logger.info("="*55)
        self.logger.info("  Packet-In Events  : %d", 
                        self.stats['packet_in_count'])
        self.logger.info("  Flow Rules Added  : %d", 
                        self.stats['flow_installed_count'])
        self.logger.info("  Direct Forwards   : %d", 
                        self.stats['direct_count'])
        self.logger.info("  Flood Events      : %d", 
                        self.stats['flood_count'])
        self.logger.info("-"*55)
        self.logger.info("  MAC TABLE for Switch %s:", dpid)
        if dpid in self.mac_to_port:
            for mac, port in self.mac_to_port[dpid].items():
                self.logger.info("    %s  →  Port %s", mac, port)
        self.logger.info("="*55 + "\n")