# =============================================================================
# SDN-Based Access Control System
# Regression Test Script
#
# Purpose:
#   Automatically verify that the access control policy is consistent.
#   Runs predefined ping tests and checks results match expected behavior.
#   This ensures whitelist rules have not regressed after any code changes.
#
# Expected Results:
#   h1 -> h2 : PASS (authorized)
#   h2 -> h1 : PASS (authorized)
#   h3 -> h1 : FAIL (unauthorized - should be blocked)
#   h3 -> h2 : FAIL (unauthorized - should be blocked)
# =============================================================================

from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.topo import Topo
from mininet.log import setLogLevel


class AccessControlTopo(Topo):
    """Same topology as topology.py — reused here for isolated regression runs."""
    def build(self):
        s1 = self.addSwitch('s1')
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')
        h3 = self.addHost('h3', ip='10.0.0.3/24')  # unauthorized
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)


def run_regression():
    setLogLevel('warning')  # suppress Mininet noise during testing

    topo = AccessControlTopo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip='127.0.0.1', port=6633
        )
    )
    net.start()

    h1 = net.get('h1')
    h2 = net.get('h2')
    h3 = net.get('h3')

    # -------------------------------------------------------------------
    # Define test cases as (sender, receiver, should_pass, description)
    # should_pass=True  means we EXPECT ping to succeed (authorized)
    # should_pass=False means we EXPECT ping to fail   (unauthorized)
    # -------------------------------------------------------------------
    tests = [
        (h1, h2, True,  "h1 -> h2 (authorized)"),
        (h2, h1, True,  "h2 -> h1 (authorized)"),
        (h3, h1, False, "h3 -> h1 (unauthorized - should be blocked)"),
        (h3, h2, False, "h3 -> h2 (unauthorized - should be blocked)"),
    ]

    print("\n" + "="*55)
    print("  REGRESSION TEST: Access Control Policy Consistency")
    print("="*55)

    all_passed = True

    for sender, receiver, should_pass, description in tests:
        # ping -c 2 = send 2 packets, -W 1 = wait max 1 second per reply
        result = sender.cmd(f'ping -c 2 -W 1 {receiver.IP()}')

        # Check if any packets were received
        received = "0 received" not in result
        passed   = (received == should_pass)

        status = "PASS ✓" if passed else "FAIL ✗"
        if not passed:
            all_passed = False

        print(f"  [{status}] {description}")

    print("="*55)
    if all_passed:
        print("  ALL TESTS PASSED — Policy is consistent ✓")
    else:
        print("  SOME TESTS FAILED — Policy regression detected ✗")
    print("="*55 + "\n")

    net.stop()


if __name__ == '__main__':
    run_regression()
