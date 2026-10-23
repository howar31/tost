# TOST Parts Runbook

A procedure for an agent asked which hardware revision the ordered vehicle
was built with (thermal module, power electronics, accessory compatibility),
answered from Tesla's official parts catalog and shop. Written to be followed
literally. Do not improvise transport or hosts.

For order-status questions, use [SKILL.md](SKILL.md). Get the VIN from
`python3 tost.py status --cached --json`. Answer in the user's conversation
language.

## Allowed hosts — hard rule

| Host | Use | Limits |
|---|---|---|
| `epcapi.tesla.com` | Catalog data API behind parts.tesla.com | read-only GET |
| `parts.tesla.com` | Parts catalog front end | read-only, browser only (see Method) |
| `epc.tesla.com` | Catalog images and documents; old catalog URL, redirects to parts.tesla.com | read-only GET |
| `shop.tesla.com` | Tesla Shop product pages | read public pages only |

- The VIN is the only personal datum that may be sent, and only to these
  hosts, because catalog fitment is keyed by VIN. Order numbers, names,
  addresses, email, account credentials and tokens never leave the machine.
- Never sign in on the user's behalf. Anything that needs a Tesla account
  (catalog-wide part search, the Shop's per-vehicle compatibility notice) is
  done by the user.
- Never write a VIN or a lookup result into tracked files: docs, tests,
  fixtures, commit messages.
- Never route through a third-party proxy, mirror, or VIN-decoder site. If a
  host blocks the request, say so and stop; do not hunt for replacements.

## Method: API first, browser only with permission

1. **API (curl).** `epcapi.tesla.com` is undocumented and may change. Observed
   endpoints:

   | Endpoint | Returns |
   |---|---|
   | `GET /api/countries` | country list, no VIN |
   | `GET /api/catalogs?countryCode=<CC>` | catalogs for a country |
   | `GET /api/catalogs/categories?VIN=<VIN>` | the VIN's catalog tree |

   The VIN tree is `responseObject[]` (categories) → `subCategories[]` →
   `systemGroups[]` (`title`, `id`, `externalReference`); each entry's
   `catalog` holds the catalog name, generation and country. It lists every
   system group in the catalog (e.g. both `SuperManifold` and
   `SuperManifold V2`), so it does not say which one the car has.

   The per-group parts list, which carries the "Original VIN part" flag, has
   no known endpoint. Do not guess paths: Akamai blocks non-browser clients
   and escalates to 403 "Access Denied" for VIN endpoints after a few probes.
   One attempt per question; a 403 means stop.

2. **When the API cannot answer** (403, or the answer needs the parts list):
   guide the user through the catalog themselves (next section). Browser
   automation is allowed only after asking the user and getting a yes for
   that lookup. If approved: Playwright WebKit (headless Chromium and Firefox
   are denied by the bot check), and route-abort every host not in the table
   above (the page loads analytics otherwise).

## Guiding the user through the catalog

1. parts.tesla.com → **VIN** tab → enter the VIN → **Search Catalog**.
2. Keep the filter on **Original Fitment** (原始安裝 in the zh-TW UI).
3. Open the system group. The entry marked **Original VIN part** is what the
   car was built with. Search-box suggestions list every variant in the
   catalog, not the car's, so always open the group page.
4. The catalog title (e.g. "Model Y Feb 2025") is when that catalog
   generation starts, not the car's build date.

Known group locations (Model Y catalog, Feb 2025 generation):

| Question | Path |
|---|---|
| Heat-pump module revision | 18 - THERMAL MANAGEMENT > 1840 - Thermal System > SuperManifold / SuperManifold V2 |
| Power Conversion System (on-board charger; V2L hardware) | 16 - HV BATTERY SYSTEM > 1630 - HV Battery Electrical Components > Ancillary Bay |

## Interpretation

Part-number meanings below come from owner reports and press coverage, not
Tesla documentation; label them as such.

| Part family | Meaning |
|---|---|
| `1547595-xx` | Super Manifold V1 |
| `1735000-xx` | Super Manifold V2 |
| `1135558-xx` | PCS (first generation): no V2L |
| `2100145-xx` | PCS2: V2L-capable (reports disagree on suffixes) |

- Tesla does not document "Original VIN part" or the Shop notice as a way to
  verify hardware. Say the lookup method is community-sourced.
- The Shop's compatibility notice is reported to be wrong at times; the
  catalog's Original VIN part wins.
- A VIN may not resolve, or may lack Original VIN part flags, before the car
  is built. Say so and suggest retrying closer to delivery.
- Hardware capability is not market availability: V2L also needs Tesla to
  enable it in that market. Do not claim a feature works from the part alone.
