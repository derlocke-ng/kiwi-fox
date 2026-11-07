# Provider modules

Provider modules — Tor, a VPN tunnel (gluetun), 9proxy, Mysterium — moved to
[kiwi-proxy](https://github.com/derlocke-ng/kiwi-proxy) with the rest of the
proxy engine in kiwi-fox 0.3.0. The contract, the lifecycle and how to write a
module are in kiwi-proxy's
[docs/plugin-system.md](https://github.com/derlocke-ng/kiwi-proxy/blob/main/docs/plugin-system.md).

From kiwi-fox's side a module is something kiwi-proxy makes an exit from, and a
profile picks that exit:

```
kiwi install kiwi-plugin-tor                  # or -vpn, -9proxy, -myst
kiwi-fox setup                                # builds the module's image (kiwi-proxy's setup)
kiwi-fox module list                          # the same as `kiwi-proxy module list`; `module countries tor`
kiwi-proxy add tor-de --module tor --country de   # the module produces the endpoint
kiwi-fox new work --exit tor-de
```

Modules install into kiwi-proxy's modules directory
(`~/.local/share/kiwi-proxy/modules/`). A module installed for kiwi-fox 0.2
(`~/.local/share/kiwi-fox/modules/`) is not looked at any more; updating its
kiwi-plugin app (0.2.0 and later) moves it, and a launch that needs it says so.
