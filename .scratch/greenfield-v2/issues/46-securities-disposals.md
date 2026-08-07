# 46 — Securities disposals

**What to build:** Share and fund sales are computed FIFO within the Depot that held them, with no holding-period exemption, and routed to the statutory category their instrument type demands.

**Blocked by:** 27, 43, 44

**Status:** ready-for-agent

- [ ] FIFO within Depot and Instrument; holding period never exempts a securities gain
- [ ] Gain is proceeds less cost basis less transaction costs, all in EUR at the rates of their respective event dates
- [ ] Currency movement on the security is part of the gain, not a separate item
- [ ] Fund gains are reduced by their partial exemption
- [ ] Share gains route to the shares category; fund, bond and certificate gains to the other-income category
- [ ] A partially consumed lot keeps its remaining basis proportionally
- [ ] Each disposal emits a Section 20 Event and computes no tax itself
- [ ] A transfer between the Admin's own Depots preserves lot identity and acquisition dates
- [ ] Tests name the paragraph each rule implements
