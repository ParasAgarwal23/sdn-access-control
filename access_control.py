# =============================================================================
# SDN-Based Access Control System
# Controller: Ryu (OpenFlow 1.3)
#
# Purpose:
#   Enforce a host whitelist. Only whitelisted IP pairs are allowed to 
#   communicate. All other IP traffic is silently dropped at the switch.
#
# How it works:
#   1. On switch connect, install a default "send-to-controller" rule
#   2. On each new IP packet_in, check if (src_ip, dst_ip) is whitelisted
#   3. If allowed  → install an allow flow rule on the switch
#   4. If blocked  → install a drop flow rule on the switch
#   Non-IP traffic (ARP etc.) is always forwarded so hosts can resolve MACs.
# =============================================================================

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4

# -----------------------------------------------------------------------------
# WHITELIST CONFIGURATION
# Add or remove (src_ip, dst_ip) tuples here to control access policy.
# Both directions must be listed if you want bidirectional communication.
# h1 (10.0.0.1) <-> h2 (10.0.0.2) : AUTHORIZED
# h3 (10.0.0.3)                    : UNAUTHORIZED (not listed here)
# -----------------------------------------------------------------------------
WHITELIST = [
    ("10.0.0.1", "10.0.0.2")  # h1 -> h2 : allowed
     # h2 -> h1 : allowed
]


class AccessControl(app_manager.RyuApp):
    """
    Ryu application that implements SDN-based access control.
    Inherits from RyuApp, which handles the OpenFlow event loop.
    """

    # Tell Ryu we are using OpenFlow version 1.3
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(AccessControl, self).__init__(*args, **kwargs)

        # MAC address table: {datapath_id: {mac_address: port_number}}
        # Used to learn which port each host is reachable on,
        # so we don't have to flood every packet.
        self.mac_to_port = {}

        # ADDED: whitelist activity log
        self.whitelist_log = set()

    # -------------------------------------------------------------------------
    # EVENT: Switch connects to controller
    # Triggered once per switch when it first connects.
    # We install a low-priority "table-miss" rule so that any packet
    # not matched by a specific rule gets sent up to this controller.
    # -------------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath          # the switch object
        ofproto  = datapath.ofproto         # OpenFlow constants
        parser   = datapath.ofproto_parser  # message builder

        # Match everything (wildcard match) at priority 0 (lowest)
        match = parser.OFPMatch()

        # Action: send packet to controller for processing
        actions = [parser.OFPActionOutput(
            ofproto.OFPP_CONTROLLER,
            ofproto.OFPCML_NO_BUFFER  # send the full packet, not just header
        )]

        self.logger.info("Switch %s connected. Installing table-miss rule.", datapath.id)
        self.add_flow(datapath, priority=0, match=match, actions=actions)

    # -------------------------------------------------------------------------
    # HELPER: Install a flow rule on the switch
    # priority    : higher number = matched first
    # idle_timeout: rule auto-expires after this many seconds of inactivity
    #               (0 = permanent)
    # actions=[]  : empty action list means DROP
    # -------------------------------------------------------------------------
    def add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser

        # Wrap actions in an instruction block (required by OF 1.3)
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions
        )]

        # Build and send the FlowMod message to the switch
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            idle_timeout=idle_timeout,
            match=match,
            instructions=inst
        )
        datapath.send_msg(mod)

    # -------------------------------------------------------------------------
    # EVENT: Packet arrives at controller (packet_in)
    # This fires when no existing flow rule on the switch matches the packet.
    # We inspect the packet, make an allow/block decision, and push a rule
    # back to the switch so future matching packets are handled at line rate.
    # -------------------------------------------------------------------------
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match['in_port']  # port the packet arrived on

        # Parse the raw packet bytes into protocol layers
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)  # Ethernet header (always present)
        ip  = pkt.get_protocol(ipv4.ipv4)          # IPv4 header (None if not IP)

        dpid = datapath.id  # unique ID of this switch

        # --- MAC Learning ---
        # Record which port this source MAC was seen on
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][eth.src] = in_port

        # Determine output port: use learned table, or flood if unknown
        dst_mac  = eth.dst
        out_port = self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD)

        # --- Access Control (IP packets only) ---
        if ip:
            src_ip = ip.src
            dst_ip = ip.dst

            if (src_ip, dst_ip) in WHITELIST:
                # ALLOWED: install a flow rule to forward future packets directly
                self.logger.info("[ALLOW] %s -> %s (port %s)", src_ip, dst_ip, out_port)

                # ADDED: log active whitelist usage
                self.whitelist_log.add((src_ip, dst_ip))
                self.logger.info("[WHITELIST LOG] %s", self.whitelist_log)

                actions = [parser.OFPActionOutput(out_port)]
                match = parser.OFPMatch(
                    eth_type=0x0800,   # 0x0800 = IPv4
                    ipv4_src=src_ip,
                    ipv4_dst=dst_ip
                )
                if out_port != ofproto.OFPP_FLOOD:
                    self.add_flow(datapath, priority=10, match=match,
                                  actions=actions, idle_timeout=0)

            else:
                # BLOCKED: install a drop rule (empty action list = drop)
                self.logger.info("[BLOCK] %s -> %s — unauthorized", src_ip, dst_ip)
                match = parser.OFPMatch(
                    eth_type=0x0800,
                    ipv4_src=src_ip,
                    ipv4_dst=dst_ip
                )
                self.add_flow(datapath, priority=10, match=match,
                              actions=[], idle_timeout=0)
                return  # drop this packet, don't forward

        else:
            # Non-IP (e.g. ARP): always forward so hosts can resolve each other's MACs
            actions = [parser.OFPActionOutput(out_port)]

        # --- Send the current packet out (before the flow rule takes effect) ---
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)
