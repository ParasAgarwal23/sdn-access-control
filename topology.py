# =============================================================================
# SDN-Based Access Control System
# Mininet Topology Script
#
# Topology:
#       h1 (10.0.0.1) ─┐
#       h2 (10.0.0.2) ──── s1 ──── RemoteController (Ryu, port 6633)
#       h3 (10.0.0.3) ─┘
#
# h1 <-> h2 : authorized (whitelisted in access_control.py)
# h3        : unauthorized — all IP traffic to/from h3 will be dropped
#
# Run this AFTER starting the Ryu controller in a separate terminal.
# =============================================================================

from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel
from mininet.cli import CLI


class AccessControlTopo(Topo):
    """
    Single-switch topology with 3 hosts.
    All hosts connect to switch s1.
    s1 connects to an external Ryu controller.
    """

    def build(self):
        # Add the switch
        s1 = self.addSwitch('s1')

        # Add authorized hosts (whitelisted in controller)
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')

        # Add unauthorized host (NOT in whitelist — traffic will be dropped)
        h3 = self.addHost('h3', ip='10.0.0.3/24')

        # Connect each host to the switch with a virtual ethernet link
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)


if __name__ == '__main__':
    setLogLevel('info')  # Mininet verbosity level

    topo = AccessControlTopo()

    # Connect to the Ryu controller running locally on port 6633
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip='127.0.0.1', port=6633
        )
    )

    net.start()

    print("\n" + "="*55)
    print("  SDN Access Control Topology Started")
    print("  h1 (10.0.0.1) <-> h2 (10.0.0.2) : AUTHORIZED")
    print("  h3 (10.0.0.3)                    : UNAUTHORIZED")
    print("="*55 + "\n")

    # Drop into Mininet CLI so you can run ping tests manually
    CLI(net)

    # Clean up virtual interfaces and processes on exit
    net.stop()
