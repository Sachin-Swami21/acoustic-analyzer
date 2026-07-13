# Bootstrapping the Jetson Orin Nano — Apple Silicon Mac edition

Box → booted **from your NVMe** → ready to run the Acoustic Analyzer, assuming your only
computer is an **Apple Silicon Mac** (with an ARM Ubuntu VM) and you have an **NVMe SSD**.

> ⚠️ **The one hard constraint.** NVIDIA's flashing tools (SDK Manager, `flash.sh`) are
> **x86-only**. Your Ubuntu VM on Apple Silicon is **ARM**, so it **cannot flash the Jetson** —
> USB passthrough won't help. We therefore avoid host-flashing entirely and do everything on
> the Jetson itself (it's arm64-native).
>
> **What your VM is / isn't for here:** you don't need it to flash. You can write the SD card
> straight from macOS. Keep the VM around for arm64 Linux dev/testing if you like, but it's not
> on the critical path.
>
> **Version target:** JetPack 6.x (Ubuntu 22.04, CUDA 12) on the Orin Nano Developer Kit.
> Confirm specifics at <https://developer.nvidia.com/embedded/jetpack> and the
> *"Jetson Orin Nano Developer Kit Getting Started"* page.

---

## The strategy (why it's shaped this way)

```
Apple Silicon Mac  ── write SD image (Balena Etcher, in macOS) ──►  microSD
                                                                       │ boot
Jetson Orin Nano ◄─────────────────────────────────────────────────────┘
   1. boot from SD   2. update + JetPack   3. move rootfs → NVMe (on-device)
   → OS now runs from the fast 256 GB NVMe; SD stays in as the boot partition
```

- **Root filesystem on NVMe** = the real speed win (OS, Ollama models, datasets all on the fast disk).
- **The SD card stays inserted** — on this no-host method it still holds the boot partition.
  Going fully SD-free (pure NVMe boot) *does* require an x86 host flash — see the fallback at the end.

---

## 0 · What you need

| Item | Notes |
|------|-------|
| Jetson Orin Nano Developer Kit | heatsink/fan attached |
| **NVMe SSD** (your 256 GB) | M.2 2280, into the Key-M slot under the module |
| microSD (64 GB+, UHS-1/A1) | the boot card |
| Kit power adapter | barrel-jack DC on the Orin Nano dev kit — don't use a weak supply |
| Monitor + **DisplayPort or HDMI**, USB keyboard + mouse | DisplayPort is the safer choice |
| Ethernet cable | wired = simplest for setup |
| **Balena Etcher** on your Mac | to write the SD image (from macOS directly) |

Install the NVMe now (power off): unscrew the standoff, seat the NVMe in the M.2 slot, screw down.

---

## 1 · Write the SD card (from macOS)

1. Download the **Jetson Orin Nano Developer Kit SD-card image** (JetPack 6.x `.img`) from the
   JetPack page above.
2. Flash it with **Balena Etcher** (simplest on macOS) → select image → select the microSD → Flash.
   *(CLI alt: `diskutil list` to find the disk, then `sudo dd if=jp6.img of=/dev/rdiskN bs=4m status=progress`.)*
3. Insert the microSD into the slot on the **underside of the module**.

> If it later refuses to boot (blank screen, no NVIDIA logo): the kit's QSPI bootloader firmware
> is likely older than this JetPack. Jump to **Fallback** at the bottom.

---

## 2 · First boot (on the Jetson)

1. Connect monitor (DisplayPort), keyboard, mouse, Ethernet, then power on.
2. Complete the Ubuntu **oobe**: language, keyboard, timezone, **username + password**, network.
3. You reach the GNOME desktop. Open a terminal and update:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```
4. Install JetPack runtime (CUDA, cuDNN, TensorRT):
   ```bash
   sudo apt install -y nvidia-jetpack
   ```
5. Max performance (helps LLM inference a lot):
   ```bash
   sudo nvpmodel -m 0     # MAXN
   sudo jetson_clocks
   ```
6. Monitoring (there is **no `nvidia-smi`** on Jetson — use `jtop`):
   ```bash
   sudo pip3 install -U jetson-stats && sudo reboot
   jtop     # confirms GPU, JetPack version, temps
   ```

---

## 3 · Move the root filesystem to the NVMe (the payoff)

Confirm the NVMe is visible, then migrate rootfs onto it with the well-known community scripts:

```bash
lsblk                       # you should see nvme0n1 (~238 GB)

git clone https://github.com/jetsonhacks/rootOnNVMe.git
cd rootOnNVMe
./copy-rootfs-ssd.sh        # formats + copies the running rootfs to the NVMe
./setup-service.sh          # points the boot chain's root= at the NVMe
sudo reboot
```

After reboot, verify the OS is now running from the SSD:
```bash
df -h /                     # the "/" mount should be /dev/nvme0n1p1, not the SD
```
That's it — the OS, models, and datasets now live on the fast NVMe. **Leave the SD card
inserted** (it holds the boot partition on this method).

---

## 4 · Set up for the Acoustic Analyzer

1. **Ollama** (arm64 installer detects Jetson CUDA and uses the GPU):
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull qwen2.5:3b
   ```
2. **Docker + NVIDIA default runtime** (for the later compose deploy):
   ```bash
   sudo usermod -aG docker $USER        # log out/in after
   sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
   { "default-runtime": "nvidia",
     "runtimes": { "nvidia": { "path": "nvidia-container-runtime", "runtimeArgs": [] } } }
   EOF
   sudo systemctl restart docker
   ```
3. **Audio front-end** — plug the **USB-A** audio adapter (fed by the soldered MAX9814 board)
   into a USB-A port:
   ```bash
   arecord -l                     # find the USB adapter's card number
   arecord -d 3 -f cd /tmp/t.wav && aplay /tmp/t.wav   # record + play back
   ```
4. **The project** (copy the folder over, or git clone):
   ```bash
   sudo apt install -y python3-venv portaudio19-dev libsndfile1   # sounddevice needs PortAudio
   cd ~/acoustic-analyzer
   python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
   ./.venv/bin/python src/capture_test.py --list      # find the USB adapter's index N
   ./.venv/bin/python src/agent.py                     # "what's that noise?"
   ```
   The code is identical to the Mac — you just pass `--device N` for the USB card.

**Getting the folder onto the Jetson (Apple Silicon, no USB flashing):** easiest is
`git clone` from a repo, or `scp` over the network from your Mac:
```bash
# from your Mac:
scp -r ./acoustic-analyzer  <jetson-user>@<jetson-ip>:~/
```

---

## 5 · Verify it's healthy

- `jtop` → GPU present, JetPack version right, temps sane.
- `df -h /` → root is on `/dev/nvme0n1p1`.
- `ollama run qwen2.5:3b "hello"` → responds; `jtop` shows a GPU spike.
- `arecord -l` → USB audio adapter listed.
- `./.venv/bin/python src/agent.py` → tool fires, it explains a sound.

---

## Fallback · if the SD image won't boot (old firmware)

Brand-new kits sometimes ship with QSPI firmware too old for JetPack 6, and updating that
firmware **does** need x86 host flashing — which your Apple Silicon Mac can't do. Options, in
order of least hassle:

1. **Match the SD image to the firmware:** try an **older JetPack SD image** (e.g. 5.1.x). If it
   boots, `sudo apt full-upgrade` and the on-device OTA can then move you forward.
2. **Borrow/rent an x86 box once:** any Intel/AMD PC with Ubuntu 22.04 runs SDK Manager for a
   one-time NVMe flash (this also gives you pure SD-free NVMe boot). A cheap used x86 mini-PC or
   a friend's laptop for an hour does it.
3. **Cloud x86 + USB:** not practical for USB flashing — skip.

Once it boots at all, everything above (§2–§4) is Apple-Silicon-friendly and needs no PC.

---

## Gotchas

- **No `nvidia-smi`** — normal on Jetson; use `jtop` / `tegrastats`.
- **Use DisplayPort** if your monitor has it — some Orin Nano + HDMI combos are flaky.
- **Underpowered supply** → random reboots under load. Use the included adapter.
- **`sounddevice` import errors** → install `portaudio19-dev`, then re-`pip install`.
- **Ollama on CPU only** → confirm `nvidia-jetpack` is installed; watch `jtop` during a run.
- **Later, in containers** → pass `--device /dev/snd` and add the container to the `audio` group,
  or the mic is silent.
