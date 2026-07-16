# Bootstrapping the Jetson Orin Nano — Apple Silicon Mac edition

Box → **JetPack 6.2 on the SD card** → **NVMe mounted as fast storage** → **headless (SSH-only)** →
ready to run the Acoustic Analyzer, from an **Apple Silicon Mac** with **no x86 PC**.

> ⚠️ **The one hard constraint.** NVIDIA's flashing tools (SDK Manager, `flash.sh`) are
> **x86-only**. An Apple Silicon Mac can't run them, and a Linux VM on Apple Silicon is **ARM**, so
> it can't flash the Jetson either (USB passthrough won't help). We therefore **avoid host-flashing
> entirely**: write the microSD straight from macOS and do everything else on the Jetson (arm64-native).
>
> **Version target:** **JetPack 6.2** = **Jetson Linux (L4T) 36.4.3**, Ubuntu 22.04, CUDA 12.
> Download page: <https://developer.nvidia.com/embedded/jetpack-sdk-62>.
> Note: JetPack **7.x dropped microSD images** (USB-installer only) — for the Mac-only path, stay on **6.2**.

---

## The strategy (why it's shaped this way)

```
Apple Silicon Mac  ── flash SD image (Balena Etcher, in macOS) ──►  microSD (64 GB)
                                                                       │ boot
Jetson Orin Nano ◄─────────────────────────────────────────────────────┘
   1. boot from SD   2. headless config (SSH, console, static IP)   3. NVMe = /mnt/nvme storage
   → OS runs from the SD card; the fast NVMe holds Ollama models + datasets
```

- **OS on the SD card, data on the NVMe.** Simple and Mac-friendly: no host flash, no rootfs
  surgery. The NVMe (`/mnt/nvme`) is where models and datasets live — that's where disk speed matters.
- **Console-only, headless.** We turn off the GNOME desktop to reclaim ~1–1.5 GB of RAM for the model,
  and drive the box entirely over SSH.
- Want the OS itself on the NVMe (avoids SD wear, faster boot)? That's an **optional** migration —
  see [§6 · Optional: move rootfs to the NVMe](#6--optional--move-the-root-filesystem-to-the-nvme).

---

## 0 · What you need

| Item | Notes |
|------|-------|
| Jetson Orin Nano Developer Kit | heatsink/fan attached; WiFi/BT M.2 card + antennas are **pre-installed** |
| **NVMe SSD** (256 GB used here → `nvme0n1` ~238 GB) | M.2 2280, Key-M slot under the module |
| microSD (64 GB+, UHS-1/A1) | the boot/OS card (SanDisk Ultra 64 GB works) |
| Kit power adapter | barrel-jack DC — don't use a weak supply (undervolt = random reboots) |
| Monitor + **DisplayPort→HDMI adapter** (or DP monitor), USB keyboard/mouse | only needed for first boot; the Orin Nano's video-out is **DisplayPort** (a ~$8 DP→HDMI adapter into any HDMI monitor works) |
| WiFi or Ethernet | either is fine; get it online during first boot |
| **Balena Etcher** on your Mac | to flash the SD image from macOS |

Install the NVMe now (power off): unscrew the standoff, seat the NVMe in the M.2 Key-M slot, screw down.

---

## 1 · Flash the SD card (from macOS)

1. Download the **JetPack 6.2 SD card image** for the Orin Nano Developer Kit:
   <https://developer.nvidia.com/embedded/jetpack-sdk-62> → *"Download JetPack 6.2 SD card image for
   Jetson Orin Nano Developer Kit"* (direct: `.../l4t/r36_release_v4.3/jp62-orin-nano-sd-card-image.zip`,
   ~7–8 GB, free NVIDIA login may be required).
2. **Do not unzip it.** In **Balena Etcher**: *Flash from file* → the `.zip` → select the microSD
   (confirm the ~64 GB target with `diskutil list`, **not** your Mac's internal disk) → Flash (~15 min).
3. When it finishes, macOS may pop **"The disk you inserted was not readable"** → click **Eject**,
   **not** Initialize (macOS just can't read the Linux partitions — that's expected).
4. Insert the microSD into the slot on the **underside of the module**.

> **Firmware note (important, but usually a non-issue on recent kits):** JetPack 6 needs the kit's
> QSPI/UEFI firmware at **≥ 36.0**. Recent kits already ship compatible — *this build's was 36.4.3,
> so no update was needed.* If the SD image **won't boot** (blank screen / boot loop), your firmware
> is older than 36.0 → see [Fallback](#fallback--sd-image-wont-boot-old-firmware).

---

## 2 · First boot (on the Jetson)

1. Connect monitor (via the DP→HDMI adapter), USB keyboard/mouse, network, then power on the barrel jack.
2. Complete the Ubuntu **oobe wizard**: language, keyboard, timezone, **username + password**
   (⚠️ write the password down — you need it for every `sudo` and for SSH), and **network**
   — if WiFi networks appear, your pre-installed antennas work; otherwise use Ethernet.
   - If asked, accept the **max APP partition size** (uses the whole card).
3. **First-boot quirks to expect (not failures):**
   - It finishes by **installing Chromium** and can **hang on the "installation finished" window**.
     Dismiss it with the **mouse** (the keyboard is sometimes dead at this screen), or drop to a text
     console with **Ctrl+Alt+F3**, log in, and `sudo reboot`.
   - Flaky USB keyboard on first boot? **Move it to a different USB port** — usually fixes it.
     (Once SSH is up in §3, you won't need the local keyboard anyway.)
4. Reach the desktop, open a terminal, and update + install the JetPack runtime:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y nvidia-jetpack        # CUDA, cuDNN, TensorRT
   sudo reboot
   ```
5. Max performance (helps LLM inference a lot):
   ```bash
   sudo nvpmodel -m 0     # MAXN / "Super" mode
   sudo jetson_clocks
   ```
6. Monitoring — there is **no `nvidia-smi`** on Jetson; use `jtop`:
   ```bash
   sudo pip3 install -U jetson-stats && sudo reboot
   jtop     # confirms GPU, JetPack version, temps
   ```

---

## 3 · Initial headless configuration

Do these in order. **Get SSH working and confirmed *before* turning off the desktop** — otherwise a
failed SSH leaves you stranded at the console.

### 3a · Enable SSH
```bash
sudo systemctl enable --now ssh
systemctl status ssh --no-pager        # want: active (running)
# if "ssh.service not found":  sudo apt install -y openssh-server && sudo systemctl enable --now ssh
```
Find the IP and connect from your Mac:
```bash
ip -4 addr show | grep inet           # on the Jetson
# on the Mac:
ssh <user>@<jetson-ip>                # first time: type "yes", then the password
```
> **Same-subnet check:** the Mac and Jetson must share a subnet (e.g. both `192.168.1.x`). If the
> Jetson landed on a different network/SSID, no firewall change helps — put both on the same WiFi.

### 3b · Static IP (via NetworkManager / `nmcli`)
Substitute your own values below — `<wifi-name>` is your SSID (from the command output), and pick a
static address on your subnet. Find your connection name and gateway first:
```bash
nmcli -t -f NAME,DEVICE,TYPE,STATE connection show --active   # note the NAME (your SSID) + interface
ip route | grep default                                       # note the gateway, e.g. 192.168.1.1
```
Pin it. Pick a **high** address to dodge the DHCP pool, or set a **router DHCP reservation** instead
(safest). Example values below — replace with yours:
```bash
sudo nmcli connection modify "<wifi-name>" \
  ipv4.method manual \
  ipv4.addresses 192.168.1.50/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "192.168.1.1 1.1.1.1"
sudo nmcli connection up "<wifi-name>"
```
> ⚠️ `connection up` **drops your SSH session** (the IP just changed). That's success — reconnect at
> the new address: `ssh <user>@<static-ip>`.

### 3c · Console-only mode (reclaim RAM)
Once SSH is confirmed working, kill the GNOME desktop so it boots to a text console:
```bash
sudo systemctl set-default multi-user.target
sudo reboot
```
Frees ~1–1.5 GB of RAM for the model; SSH is unchanged. The monitor now shows a text login (unplug it
whenever). Reverse anytime: `sudo systemctl set-default graphical.target` (or `start graphical.target`
for a one-off).

---

## 4 · Set up the NVMe as storage (`/mnt/nvme`)

The blank NVMe (`nvme0n1`, ~238 GB) becomes a fast disk for models + datasets. **These commands erase
the NVMe** — verify every one targets **`nvme0n1`**, never the SD card (`mmcblk*`).

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT      # confirm nvme0n1 is blank (no fstype/mountpoint)

# 1. Partition (GPT, one full partition) + format ext4
sudo parted /dev/nvme0n1 --script mklabel gpt
sudo parted /dev/nvme0n1 --script mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L nvme /dev/nvme0n1p1

# 2. Mount + take ownership (write without sudo)
sudo mkdir -p /mnt/nvme
sudo mount /dev/nvme0n1p1 /mnt/nvme
sudo chown -R $USER:$USER /mnt/nvme

# 3. Auto-mount on every boot (UUID + nofail so a missing drive never blocks boot)
echo "UUID=$(sudo blkid -s UUID -o value /dev/nvme0n1p1) /mnt/nvme ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab

# 4. Verify
sudo systemctl daemon-reload && sudo mount -a
df -h /mnt/nvme                                 # ~234 GB mounted at /mnt/nvme
```

---

## 5 · Set up for the Acoustic Analyzer

### 5a · Ollama — with models on the NVMe
The arm64 installer detects the Jetson's CUDA and uses the GPU:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version && systemctl status ollama --no-pager     # want: active (running)
```
**Redirect model storage to the NVMe** (default is the SD card). The service runs as user `ollama`,
so a systemd drop-in sets `OLLAMA_MODELS`:
```bash
sudo mkdir -p /mnt/nvme/ollama
sudo chown -R ollama:ollama /mnt/nvme/ollama

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'EOF'
[Service]
Environment="OLLAMA_MODELS=/mnt/nvme/ollama"
EOF

sudo systemctl daemon-reload && sudo systemctl restart ollama
```
Pull the model and confirm it landed on the NVMe:
```bash
ollama pull qwen2.5:3b            # ~1.9 GB; chosen for strong tool-calling
ls /mnt/nvme/ollama/blobs         # blob files here = models are on the NVMe
ollama run qwen2.5:3b "hello"     # responds; watch jtop for a GPU spike
```
> Low on RAM (4 GB Jetson)? Use `qwen2.5:1.5b`.

### 5b · Audio front-end
Plug the **USB-A** audio adapter (fed by the soldered MAX9814 board) into a USB-A port:
```bash
arecord -l                     # find the USB adapter's card number
arecord -d 3 -f cd /tmp/t.wav && aplay /tmp/t.wav   # record + play back
```

### 5c · Deploy the stack

The whole stack — Ollama (GPU), the DSP tool service, and the terminal UI — runs on **k3s**, with
images built and pushed without sudo via an in-cluster registry. Full runbook →
**[DEPLOY-K3S.md](DEPLOY-K3S.md)**.

---

## 6 · Optional · move the root filesystem to the NVMe

Only if you want the **OS itself** on the NVMe (faster boot, less SD wear). Not required — §4's
storage mount already puts the heavy data (models/datasets) on the NVMe. This reformats the NVMe, so
do it **before** §4 (or back up `/mnt/nvme` first):

```bash
git clone https://github.com/jetsonhacks/rootOnNVMe.git
cd rootOnNVMe
./copy-rootfs-ssd.sh        # formats + copies the running rootfs to the NVMe
./setup-service.sh          # points the boot chain's root= at the NVMe
sudo reboot
df -h /                     # "/" should now be /dev/nvme0n1p1, not the SD card
```
**Leave the SD card inserted** — on this no-host method it still holds the boot partition. (Pure
SD-free NVMe boot requires a one-time x86 host flash.)

---

## 7 · Verify it's healthy

- `jtop` → GPU present, JetPack version right, temps sane.
- `df -h /mnt/nvme` → NVMe mounted (~234 GB).
- `ls /mnt/nvme/ollama/blobs` → model blobs are on the NVMe.
- `ollama run qwen2.5:3b "hello"` → responds; `jtop` shows a GPU spike.
- `ssh <user>@<static-ip>` from the Mac → lands at the console (static IP + SSH working).
- `arecord -l` → USB audio adapter listed (on the host).
- `docker build -t acoustic-analyzer .` → image builds; `docker run … python src/agent.py` → tool fires, it explains a sound.

---

## Fallback · SD image won't boot (old firmware)

If the JetPack 6.2 SD image won't boot (blank screen / boot loop), the kit's QSPI firmware is older
than 36.0. Recent kits (this one included) already ship ≥ 36.0, but older stock needs a one-time
update. Since Apple Silicon can't host-flash, use the **microSD-only bridge path**:

1. Check firmware: monitor + keyboard, power on, spam **Esc** into UEFI, read the version line.
2. If < 36.0: flash + boot the **JetPack 5.1.3** image (`jp513-orin-nano-sd-card-image.zip`,
   from <https://developer.nvidia.com/embedded/jetpack-sdk-513>), finish setup, get online.
3. `sudo reboot` (runs the bootloader firmware update — watch the monitor, **don't cut power**).
4. `sudo apt update && sudo apt install nvidia-l4t-jetson-orin-nano-qspi-updater` → `sudo reboot`.
5. Re-flash the **same** microSD with the JetPack 6.2 image (§1) and boot.

Alternative: borrow an x86 Ubuntu PC once and run SDK Manager (also enables pure SD-free NVMe boot).

---

## Gotchas

- **No `nvidia-smi`** — normal on Jetson; use `jtop` / `tegrastats`.
- **Video-out is DisplayPort** — a cheap DP→HDMI adapter into any HDMI monitor works (needed only for first boot).
- **First-boot Chromium window hangs** — dismiss with the mouse, or Ctrl+Alt+F3 → `sudo reboot`.
- **Flaky USB keyboard on first boot** — move it to a different USB port.
- **Underpowered supply** → random reboots under load. Use the included adapter.
- **Enable SSH *before* going console-only** — or a failed SSH strands you.
- **Static IP drops your SSH session** on apply — reconnect at the new address (expected).
- **Don't unplug the WiFi antennas** — the MHF4 connectors are fragile and pre-seated from the factory.
- **Keep host clean — no host Python** → the app runs in Docker (§5d); don't `apt install` python/pip on the host.
- **Container mic is silent** → the `docker run` needs **both** `--device /dev/snd` **and** `--group-add audio`.
- **Container can't reach Ollama** → run with `--network host` and set `-e OLLAMA_HOST=http://localhost:11434` (Ollama lives on the host, §5a).
- **`sounddevice`/PortAudio errors in the image** → the Dockerfile must install `libportaudio2` + `libsndfile1` (runtime libs).
- **Ollama on CPU only** → confirm `nvidia-jetpack` is installed; watch `jtop` during a run.
- **Ollama models filling the SD card** → confirm the `OLLAMA_MODELS` drop-in (§5a) and that blobs are under `/mnt/nvme/ollama`.
