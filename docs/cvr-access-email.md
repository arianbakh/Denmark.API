# CVR system-to-system access — email draft (English)

To: cvrselvbetjening@erst.dk
Subject: Request for system-to-system (Elasticsearch) access to CVR data

---

Dear Danish Business Authority,

We would like to request system-to-system access to CVR data via the Elasticsearch
distribution (distribution.virk.dk/cvr-permanent), for the purpose of building a data platform using publicly available Danish data.

To speed things up, here are some details we expect you may need:
- Company: Gather Mind ApS
- CVR: 46636562
- Contact: Arian Bakhtiarnia
- Email: <CONTACT_EMAIL — see secrets/secrets.env>
- Phone: <CONTACT_PHONE — see secrets/secrets.env>
- Static IPv4 for whitelisting: <VPS_IP — see secrets/secrets.env>

Could you please let us know the steps to obtain a user ID and password for the Elasticsearch
distribution, and any further information you need from us?

Kind regards,
Arian Bakhtiarnia
Director
Gather Mind ApS

---

## Verified vs. unverified (2026-07-23)
- VERIFIED (official + practitioner sources): contact = cvrselvbetjening@erst.dk; must sign a
  declaration about reklamebeskyttede enheder; there is processing time; access details are
  sent by email AFTER you contact them.
- NOT documented publicly (so we ASK rather than assume): whether you must send your CVR
  number, and whether an IP address must be whitelisted / IPv4-only. Earlier IPv4 claim came
  from an unconfirmed search summary — do not act on it until ERST confirms.

## Fill in before sending
- Surname, phone
- VPS static IPv4 (from Hetzner console — provision it first; see README)

## After they reply
- Sign and return the declaration.
- I'll wire the WireGuard gateway (GPU box egresses via the VPS IP) before the data pull.
