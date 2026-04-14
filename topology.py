# topology.py

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink

def create_topology():
    setLogLevel('info')

    net = Mininet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink
    )

    c0 = net.addController('c0', controller=RemoteController,
                            ip='127.0.0.1', port=6633)

    s1 = net.addSwitch('s1', protocols='OpenFlow13')

    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    net.addLink(h1, s1)
    net.addLink(h2, s1)
    net.addLink(h3, s1)
    net.addLink(h4, s1)

    print("\nTopology: h1,h2,h3,h4 → Switch s1 → Ryu Controller")
    print("IPs: 10.0.0.1 to 10.0.0.4\n")

    net.build()
    c0.start()
    s1.start([c0])

    print("=== TEST COMMANDS ===")
    print("h1 ping h2 -c 5          # basic ping")
    print("pingall                   # ping all hosts")
    print("sh ovs-ofctl dump-flows s1  # view flow table")
    print("="*40)

    CLI(net)
    net.stop()

if __name__ == '__main__':
    create_topology()