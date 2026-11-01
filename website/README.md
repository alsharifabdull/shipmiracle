# Website (shipmiracle.com)

The public website: plain HTML, CSS and JS, no build step. It is served from the owner's VPS, and the same folder is exported with the public release.
It must be served at the domain ROOT, because every path in the pages is absolute (`/assets/...`, `/styles.css`). nginx needs `error_page 404 /404.html;`.
To publish: copy the contents of this folder to the web root of the server (`CNAME` and this README are not needed there).
Fonts are Geist (latin, variable) under the SIL Open Font License; the license text is `assets/fonts/OFL-geist.txt`.
