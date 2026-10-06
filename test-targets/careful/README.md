# Careful tags

A web run tests fully by default: it clicks, types, submits, buys and changes settings
(#299). A file here, named after the product (`<product>.json`, the same name as
`WEB_GUI_PRODUCT`), marks the parts where the Driver should only look:

```json
{
  "about": "Why these parts need care.",
  "everything": false,
  "routes": ["/#/payment", "/#/administration"],
  "controls": ["Delete account"]
}
```

- `everything: true` makes the whole target careful.
- A route covers the routes under it.
- A control matches when its name contains the text, in any case.

`WEB_GUI_CAREFUL` adds tags for one run: comma-separated routes and control names, or `*`.
On a careful part, the read-only safety gate decides each step. Logging out and leaving
the site are refused everywhere. The local test targets need no file: they're throwaway
copies, so nothing on them is tagged.
