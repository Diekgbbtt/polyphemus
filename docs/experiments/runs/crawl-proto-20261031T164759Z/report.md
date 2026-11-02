# Local crawl prototype

- Target: `https://the-internet.herokuapp.com/`
- Session: `crawl-proto-20261031T164759Z`
- Stop: `session_deadline`
- Policy: deterministic impact order, no Jev
- Auth: public fixture, no oracle
- Pages: 59
- Actions: 220
- Flows: 1208
- Endpoints: 81
- Parameters: 5
- Scripts: 24
- Removed: 8
- External links: 3
- Downloads: 187
- Errors: 0

## Pages

- https://the-internet.herokuapp.com/ | status 200 | The Internet
- https://the-internet.herokuapp.com/abtest | status 200 | The Internet
- https://the-internet.herokuapp.com/add_remove_elements/ | status 200 | The Internet
- chrome-error://chromewebdata/ | status None | 
- https://the-internet.herokuapp.com/broken_images | status 200 | The Internet
- https://the-internet.herokuapp.com/canvas | status 200 | The Internet
- https://the-internet.herokuapp.com/challenging_dom | status 200 | The Internet
- https://the-internet.herokuapp.com/checkboxes | status 200 | The Internet
- https://the-internet.herokuapp.com/checkboxes? | status 200 | The Internet
- https://the-internet.herokuapp.com/context_menu | status 200 | The Internet
- chrome-error://chromewebdata/ | status None | 
- https://the-internet.herokuapp.com/disappearing_elements | status 200 | The Internet
- https://the-internet.herokuapp.com/about/ | status 404 | 
- https://the-internet.herokuapp.com/contact-us/ | status 404 | 
- https://the-internet.herokuapp.com/portfolio/ | status 404 | 
- https://the-internet.herokuapp.com/drag_and_drop | status 200 | The Internet
- https://the-internet.herokuapp.com/dropdown | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_content | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_content?with_content=static | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_controls | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_controls? | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_loading | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_loading/1 | status 200 | The Internet
- https://the-internet.herokuapp.com/dynamic_loading/2 | status 200 | The Internet
- https://the-internet.herokuapp.com/entry_ad | status 200 | The Internet
- https://the-internet.herokuapp.com/exit_intent | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/download | status 200 | The Internet
- https://the-internet.herokuapp.com/upload | status 200 | The Internet
- chrome-error://chromewebdata/ | status None | the-internet.herokuapp.com
- https://the-internet.herokuapp.com/floating_menu | status 200 | The Internet
- https://the-internet.herokuapp.com/forgot_password | status 200 | The Internet
- https://the-internet.herokuapp.com/login | status 200 | The Internet
- https://the-internet.herokuapp.com/frames | status 200 | The Internet
- https://the-internet.herokuapp.com/nested_frames | status 200 | 
- https://the-internet.herokuapp.com/frame_top | status 200 | 
- https://the-internet.herokuapp.com/frame_left | status 200 | 
- https://the-internet.herokuapp.com/frame_middle | status 200 | 
- https://the-internet.herokuapp.com/frame_right | status 200 | 
- https://the-internet.herokuapp.com/frame_bottom | status 200 | 
- https://the-internet.herokuapp.com/iframe | status 200 | The Internet

## Removed

- clickable `Delete` | forbidden_control
- clickable `Delete` | forbidden_control
- clickable `delete` | forbidden_control
- clickable `delete` | forbidden_control
- form `E-mail Retrieve password` | forbidden_form
- form `E-mail Retrieve password` | forbidden_form
- form `Username Password Login` | forbidden_form
- form `Username Password Login` | forbidden_form

## External

- http://elementalselenium.com/
- https://saucelabs.com/
- https://www.tiny.cloud/powered-by-tiny?utm_campaign=poweredby&utm_source=tiny&utm_medium=referral&utm_content=v6

## Deviations

- The Jev policy is replaced by a deterministic impact order.
- The HTTP-history edge and the graph curator are not exercised; the flows are local evidence.
- Standalone input/select/textarea controls are outside the element map and are not exercised.
- Per-page action and form caps bound the prototype.
- Iframe and shadow content is walked; OOPIF and worker auto-attach is not enabled.
- Form result pages are recorded, not traversed as new pages.
- Source maps are not fetched.
