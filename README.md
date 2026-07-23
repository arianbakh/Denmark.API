# DenmarkAPI

Public Danish data → LLM-processed → joined data lake, queryable to spin up B2B/B2C products.
Phase 1 focus: restaurant/food-inspection (smiley) data + CVR company & accounting data.
First product: a map of all food businesses (incl. new ones with no report yet) with parsed
inspection history (e.g. rat issues, with dates/counts/resolution/penalty), viewable +
English-translated PDFs, plus CVR/accounting data.

---

# YOUR ACTION ITEMS
Do these, then report back. I take it from there.

## 1. Machine setup (needs sudo)

### 1a. Mount external 4TB SSD (keep exFAT — Windows-readable backup)
- Create the mount point:
  ```bash
  sudo mkdir -p /mnt/ext
  ```
- Add it to fstab (auto-mount by UUID):
  ```bash
  echo "UUID=$(sudo blkid -s UUID -o value /dev/sda1) /mnt/ext exfat defaults,uid=1000,gid=1000,nofail 0 0" | sudo tee -a /etc/fstab
  ```
- Mount it now:
  ```bash
  sudo mount -a
  ```

### 1b. Docker + Compose
- Install Docker:
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  ```
- Add yourself to the docker group (then LOG OUT/IN):
  ```bash
  sudo usermod -aG docker $USER
  ```

### 1c. NVIDIA Container Toolkit (GPU in Docker) + fio
- Add the toolkit's GPG key:
  ```bash
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  ```
- Add the apt repo:
  ```bash
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
  ```
- Install toolkit + fio:
  ```bash
  sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit fio
  ```
- Wire the toolkit into Docker and restart:
  ```bash
  sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
  ```

### 1d. Verify (should print the GPU table)
```bash
docker run --rm --gpus all ubuntu nvidia-smi
```

## 2. Hetzner VPS (do now — gives us a static IPv4 to include in the email)
- Create a Hetzner CX22 (~€4/mo). Note its public IPv4 from the console.
- Add this machine's SSH public key to the VPS (Hetzner → SSH keys):
  ```
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIA5yZmbcVgbXPrmPU9ObW+5g44Z1q02tSt0UOa3qd9n9 denmarkapi-gpu-GatherMindGPU
  ```
- Provisioning now (vs. waiting) front-loads the IP so ERST doesn't need a slow second round.
- WireGuard wiring comes later — I'll handle it before the data pull.

## 3. CVR access email
- Open `docs/cvr-access-email.md`, fill surname + phone + the VPS IPv4, send to
  cvrselvbetjening@erst.dk.
- Forward me their reply when it arrives.

## 4. Rejseplanen Labs account (free — do now, human-in-the-loop)
- Register at labs.rejseplanen.dk → get an API key (free 50k calls/month non-commercial quota).
- Purpose: verify what real-time feeds exist (esp. live vehicle GPS positions) from the one
  clearly-licensed national source (CC BY 4.0). Transport is backlog, but the account isn't.
- Report back the API key (or that you've made it) + anything it lists about real-time/vehicle data.

## Report back to me
- Output of the `docker run --gpus all` verify command.
- Confirm `/mnt/ext` is mounted (`df -h /mnt/ext`).
- The VPS IPv4 (and root SSH access when you're ready for me to set up WireGuard).
- Rejseplanen Labs API key.
- ERST's reply when it arrives.

## 5. GPU autostart (reboot-proof) — one-time sudo
Makes the harvest + dashboard-push resume automatically after a GPU reboot/poweroff.
```bash
pkill -f "denmarkapi\." 2>/dev/null   # stop the manual (setsid) instances first
sudo cp systemd/denmarkapi-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now denmarkapi-harvest.service denmarkapi-dashpush.service
```
(Harvest is resumable, so it picks up where it left off. VPS services already autostart.)

## Dashboard
- URL + credentials are in `secrets/secrets.env` (DASH_URL / DASH_USER / DASH_PASS).
- Open DASH_URL in your laptop browser; shows harvest progress + aggregated errors, refreshes
  every 5s. Served from the always-on VPS, so it works even when the GPU box is off (it shows
  how stale the snapshot is). NOTE: HTTP Basic Auth over plain HTTP — fine for now; HTTPS later.

---

## Storage
- **Working data on NVMe** (`./data`, 1.7 TB free) — hot data, weights, Parquet, PDF text.
- **External `/mnt/ext`** (exFAT) — personal backup + raw-PDF archive + overflow. Move data here
  once NVMe is ~half full.

## Docs
- `CLAUDE.md` — full context/decisions. `todo.md` — phased plan.
- `docs/cvr-access-email.md` — access request. `docs/tilbudsavis-sources.md` — offer-flyer sources + terms.
