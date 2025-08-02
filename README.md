<img width="1013" height="226" alt="NRTV" src="https://github.com/user-attachments/assets/cb42d106-0641-4086-8c39-03a8600760bb" />

# Northern Rivers Television

*Emulated Northern Rivers TV Experience – self‑hosted IPTV with every local channel mirror and a slick web UI.*

---

## Features

* **Full channel lineup** – ABC, SBS, Seven, Nine, Ten, NITV, community & shopping channels; matches the Lismore / Northern Rivers OTA list.
* **Instant switching** – < 250 ms change‑over on a local network (HLS low‑latency mode).
* **Dynamic EPG** – automatic sync with XMLTV; live "now/next" cards, progress bars, late‑run correction.
* **Audio & radio channels** – stream radio services right from the guide.
* **Responsive UI** – currently optimised for PC and TV, mobile phone styling coming soon.
* **CLI splash‑screen** – fancy UTF‑8 box on startup with status info.
* **No vendor lock‑in** – 100 % open‑source Flask + vanilla JS; keep your data in your house.

---

## Quick Start

```bash
# 1. Grab the code
$ git clone https://github.com/lolitemaultes/NRTV.git
$ cd NRTV

# 2. Create a virtualenv
$ python3 -m venv .venv && source .venv/bin/activate

# 3. Install deps
$ pip install -r requirements.txt

# 4. Fire it up
$ python server.py
```

Open the URL in any modern browser – you’ve got a full‑blown Free TV.

---

## Folder Structure

```
├── smart_tv.html
├── server.py
```

---

## Channel Line‑up (sample)

| LCN | Channel              |
| --- | -------------------- |
| 2   | ABC TV               |
| 3   | SBS World News       |
| 5   | 10 HD                |
| 6   | 7 HD                 |
| 8   | Nine Northern Rivers |
| 20  | ABC HD               |
| 21  | ABC News             |
| 22  | ABC Kids / Family    |
| 23  | ABC ME               |
| 24  | ABC News 24          |
| 30  | SBS One HD           |
| 31  | SBS Viceland HD      |
| 32  | SBS World Movies     |
| 33  | SBS Food             |
| 34  | NITV HD              |
| 35  | SBS WorldWatch       |
| 50  | 10 HD                |
| 51  | 10 Drama             |
| 52  | 10 Comedy            |
| 53  | Sky News Regional    |
| 54  | Gecko                |
| 55  | GOLD                 |
| 56  | YOU TV               |
| 60  | 7 HD Lismore         |
| 62  | 7TWO HD              |
| 64  | 7mate HD             |

---

## Roadmap

* ✍️ *PVR recording & catch‑up*
* ✍️ *Subtitle overlay (WebVTT)*

---

## Legal

Streams are sourced from publicly accessible endpoints. Verify the licensing for your region before rebroadcasting. This repo is for educational/personal use. **No warranty.**

---

## Credits

* [@matthuisman](https://github.com/matthuisman) for the excellent i.mjh.nz playlists & EPG.
* Icons: [Material Design Icons](https://materialdesignicons.com/).
* Emoji: Twemoji.

---

## License

```
see LICENSE.md
```
