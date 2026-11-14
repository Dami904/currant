# Currant brand files

| File | Use it for |
| --- | --- |
| `currant-mark.svg` | The mark alone, on any background |
| `currant-app-icon.svg` | The mark on a dark rounded tile (favicon, avatar, social card) |
| `currant-logo.svg` | Mark and wordmark, for light backgrounds |
| `currant-logo-dark.svg` | Mark and wordmark, for dark backgrounds |

Colours: amber `#f0b46e`, verdigris `#2a8a79`, coral `#ec8a72`, spruce `#0e5a52`, night `#072a29`.

The wordmark is set as SVG text in the system sans-serif, so it can render slightly differently
from one machine to the next. The mark is pure shapes and looks the same everywhere.

To put the logo in a README so it follows GitHub's light or dark theme:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/currant-logo-dark.svg">
  <img src="docs/brand/currant-logo.svg" alt="Currant" width="200">
</picture>
```
