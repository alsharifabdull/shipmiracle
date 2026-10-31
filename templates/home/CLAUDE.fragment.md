## Stack rules — Home automation (Python + devices)
- Everything in the Python stack rules applies.
- Live devices, hubs and SSH targets are production. Reading state is allowed; any action
  that switches, configures or restarts a device needs the owner's explicit yes for that action.
- Configuration validation (schema, dry-run) is not proof the automation works; record
  runtime evidence separately from static checks.
- Keep a `live/` note of what is deployed where, with version and date, in `docs/STATUS.md`.
- Browser checks of dashboards through the `playwright` plugin or the built-in browser pane.
