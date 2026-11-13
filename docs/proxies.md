# Proxies and provider modules

A profile goes out through an **exit**: a named proxy connection that
kiwi-proxy keeps, such as a SOCKS5 proxy you were given or a connection that a
provider module makes for you through Tor or a VPN. This page says how you put
a profile on an exit, what profiles on one exit share, and how provider
modules fit in. How exits work in detail is on
[kiwi-proxy's pages](https://kiwi-network.eu/docs/clients/kiwi-proxy/).

## kiwi-fox makes no proxies

You define an exit once, in kiwi-proxy, and then put profiles on it:

```bash
kiwi-proxy add work socks5://user:pass@proxy.example.net:1080
kiwi-fox new shop --exit work
```

`kiwi-proxy add` takes `socks5://…`, `http://…`, `https://…` or the
`host:port:user:pass` format that many proxy vendors hand out. The **Kiwi
Proxy** app does the same; the **New profile** dialog of Kiwi Fox has an
**Open Kiwi Proxy** button for it. `--exit` takes the exit's name or the start
of its id, as `kiwi-proxy list` shows them.

If you give `kiwi-fox new` an address instead of an exit, it tells you the
`kiwi-proxy add` command to run. To try an address without saving anything,
`kiwi-fox test socks5://…` shows the IP address, country, city, timezone and
network the proxy comes out at.

## Profiles on one exit share it

Several profiles can use the same exit, and so can kiwi-pentesting's tools and
programs on the host. They all share the exit's **gateway**: one network
namespace (a separate network stack with its own routes and firewall), one
exit IP address and one set of Tor circuits. Identities that must not share an
IP address need different exits.

The exit's own settings belong to kiwi-proxy: its address and password, its
DNS mode and its blocklists. You change them with `kiwi-proxy set` or in the
Kiwi Proxy app, and every profile on the exit gets the change at its next
start. kiwi-fox never writes an exit's settings.

To move a profile to another exit, or take it off its exit:

```bash
kiwi-fox set shop --exit other
kiwi-fox set shop --no-proxy
```

## No proxy

A profile created with `--no-proxy` uses this machine's own connection. It has
no gateway: its browser container has a network of its own, and nothing is
sealed, which means that its traffic can go anywhere your machine can reach.
A Tor Browser profile cannot run without a proxy, and `selfcheck` needs an
exit.

## Where a profile goes out

The exit's country, city and IP address that a profile's row and
`kiwi-fox show` print are kiwi-proxy's record of the exit. kiwi-proxy measures
an exit when it comes up, when you run `kiwi-proxy check EXIT`, and when a
profile starts on it. A profile with no proxy keeps its own record of this
machine's connection.

## Provider modules

A provider module is a small Kiwi app that makes an exit's upstream for you:
Tor, a VPN tunnel (gluetun), 9proxy or Mysterium. Modules belong to
kiwi-proxy. You install one, let `setup` build its image, and make an exit on
it in kiwi-proxy:

```bash
kiwi install kiwi-plugin-tor            # or kiwi-plugin-vpn, -9proxy, -myst
kiwi-fox setup                          # runs kiwi-proxy's setup, which builds the module's image
kiwi-proxy add tor-de --module tor --country de
kiwi-fox new shop --exit tor-de
```

`kiwi-fox module …` is the same as `kiwi-proxy module …`. For example,
`kiwi-fox module list` shows the installed modules and
`kiwi-fox module countries tor` the countries a module can go out in. A VPN
exit that does not answer shows "VPN not answering" on the
profile's row until the VPN server answers again.

How each module works is on
[kiwi-proxy's provider module page](https://kiwi-network.eu/docs/clients/kiwi-proxy/modules/),
and how to write one on
[Writing a provider module](https://kiwi-network.eu/docs/clients/kiwi-proxy/plugin-system/).

## DNS data

The resolver in each gateway uses kiwi-proxy's DNS data: the list of
DNS-over-HTTPS resolvers and the blocklists. `kiwi-fox setup` downloads it,
and kiwi-proxy's timer refreshes the blocklists once a day. These commands do
the same by hand:

```bash
kiwi-fox dns sync                 # the list of resolvers
kiwi-fox dns update               # the default blocklist, oisd big
kiwi-fox dns update oisd-small    # another list
```
