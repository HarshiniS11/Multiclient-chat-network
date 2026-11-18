
"""Mininet topology for the multi-client chat network."""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class ChatTopology(Topo):
    def build(self):
        switch = self.addSwitch(
            "s1",
            protocols="OpenFlow13",
            failMode="secure",
        )

        for name, ip in [
            ("h1", "10.0.0.1/24"),
            ("h2", "10.0.0.2/24"),
            ("h3", "10.0.0.3/24"),
            ("srv", "10.0.0.10/24"),
        ]:
            host = self.addHost(name, ip=ip)
            self.addLink(host, switch)


def run():
    net = Mininet(
        topo=ChatTopology(),
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True,
        build=False,
    )
    net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6653,
    )

    net.build()
    net.start()
    info("*** Chat topology started. Run pingall to test.\n")

    try:
        CLI(net)
    finally:
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
