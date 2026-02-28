# Livestream + VR Pipeline — Stretch Goal Pitch
## For: Alex C | Duration: 15 min | Gate: T2 must PASS first
## Date: 2026-03-03 | Status: RESEARCH DRAFT

---

## What We Already Have (from T1/T2 Sprint)

| Component | Status | Details |
|-----------|--------|---------|
| RTX A6000 | Operational | 48 GB VRAM, CUDA 12.4, torch 2.6.0 |
| ComfyUI v0.12.3 | Operational | 30+ custom nodes including ControlNet, LayerDiffuse, RMBG, LTXVideo, frame interpolation, Ollama |
| ArtBot pipeline | Operational | 5 tools (generate, animate, brief, review, promote) + label, 68 tests |
| EdBot pipeline | Operational | 28 tools, 46+ endpoints, FastAPI :8901, 1081 tests |
| Resolve Studio 20.3.1.6 | Operational | IPC bridge confirmed, 6 API capabilities live-tested |
| Ollama | Operational | 9 models (162 GB), 127.0.0.1:11434, includes vision-capable models |
| Blender MCP | Configured | 7 tools for automated Blender operations |
| onnxruntime | Installed | v1.24.1, GPU-accelerated inference |
| torch + CUDA | Installed | 2.6.0+cu124, production-grade ML stack |

**Not installed:** Unreal Engine, diffusers, TripoSR. No Unreal on disk.

---

## T3: AI Livestreaming (Weeks 4-5)

### T3a — Real-Time AI Face Filter Stream

**What it is:** iPhone captures face → AI transforms appearance in real-time → OBS outputs to stream.

**Pipeline:**
```
iPhone (Live Link Face) → facial blendshapes → ComfyUI StreamDiffusion (img2img)
  → style-transferred face → OBS virtual camera → Twitch/YouTube Live
```

**What exists today:**
- ComfyUI_StreamDiffusion node pack (github.com/jesenzhang/ComfyUI_StreamDiffusion)
  - Real-time img2img with TensorRT acceleration
  - SD-turbo + LCM-LoRA support for fast generation
  - Stochastic Similarity Filter reduces redundant frame processing
  - Batch size = 1 for img2img mode
- Live Link Face app v1.6.0 (Feb 2026) — iOS + Android (June 2025 beta)
  - Streams solved facial animation data over network
  - Supports up to 120 FPS with non-TrueDepth cameras
  - Now works with iPhone 12+

**Gap analysis:**
- StreamDiffusion ComfyUI node is NOT currently installed — requires `pip install` + node clone
- Live Link Face natively targets Unreal MetaHuman, NOT ComfyUI
- **No direct Live Link Face → ComfyUI bridge exists** — would need custom WebSocket relay
- Alternative: use ComfyUI_RealtimeNodes (MediaPipe face tracking) with webcam directly, skip iPhone
- VRAM: SD-turbo img2img ~4-6 GB, leaves headroom on A6000

**Honest assessment:** Medium maturity. StreamDiffusion works for webcam img2img. Live Link Face integration would require custom bridging code. Webcam-only path is simpler and proven.

### T3b — Style Transfer Livestream

**What it is:** Live webcam → ControlNet pose-preserving style transfer → OBS output.

**Pipeline:**
```
Webcam feed → ComfyUI (ControlNet OpenPose + StreamDiffusion)
  → Art Deco / custom style applied to every frame
  → OBS capture → stream output
```

**What exists today:**
- comfyui-advanced-controlnet already installed on ENKI64
- StreamDiffusion provides the real-time loop
- ControlNet OpenPose preserves body/face structure while changing style
- No additional hardware needed — webcam + existing GPU

**Gap analysis:**
- StreamDiffusion node needs installing (not currently in custom_nodes)
- ControlNet + StreamDiffusion combined workflow needs authoring
- Latency target: <100ms per frame for "real-time" feel
- VRAM: ControlNet ~2-4 GB + StreamDiffusion ~4-6 GB = ~8-10 GB (fine on 48 GB)

**Honest assessment:** High feasibility. All components exist as ComfyUI nodes. Integration is workflow authoring, not new code. This is the strongest T3 demo candidate.

---

## T4: VR Streaming (Weeks 5-6)

### T4a — AI 3D Asset Generation

**What it is:** ComfyUI generates texture/image → single-image-to-3D model → Blender cleanup → export for VR scene.

**Pipeline:**
```
ComfyUI (text/image gen) → TripoSR / TRELLIS.2 (image → 3D mesh)
  → Blender MCP (automated cleanup, UV, export) → glTF/FBX asset
```

**What exists today:**

| Model | VRAM | Speed | Quality | ComfyUI Node |
|-------|------|-------|---------|--------------|
| TripoSR | 6-8 GB (half-precision) | Sub-second mesh gen | Good for previews | ComfyUI-Flowty-TripoSR |
| InstantMesh | 8-10 GB | 10-30s | Better organic forms | ComfyUI-3D-Pack |
| TRELLIS.2 (Microsoft) | 12-24 GB | ~3s on H100 | Best quality, PBR materials | ComfyUI-3D-Pack |
| LGM (3D Gaussians) | ~10 GB | 10-30s | Fast Gaussian conversion | ComfyUI-3D-Pack |

- ComfyUI-3D-Pack: comprehensive node suite supporting TripoSR, InstantMesh, TRELLIS.2, Hunyuan3D-2, TripoSG
- Blender MCP already configured with 7 tools for automated operations
- glTF 2.0 is the recommended export format for Blender → Unreal (preserves textures accurately)
- Unreal Pipeline Tools add-on v2.0.0 (Jan 2026) fixes scaling issues via glTF pipeline

**Gap analysis:**
- ComfyUI-3D-Pack NOT installed — requires setup + model downloads
- TripoSR model weights need downloading from HuggingFace (~1-2 GB)
- TRELLIS.2 needs 12-24 GB VRAM — fits on A6000 but limits concurrent operations
- **Unreal Engine is NOT installed on ENKI64** — major gap for T4b
- Blender → Unreal pipeline has known UE 5.5 reimport regressions (use glTF to mitigate)

**Honest assessment:** Image → 3D mesh is proven technology with multiple ComfyUI options. Blender MCP automation is ready. The gap is Unreal Engine installation + the "last mile" of getting assets into a live VR scene.

### T4b — Virtual Set VR Streaming

**What it is:** Unreal Engine renders a virtual set populated with AI-generated assets, streamed to browser/headset via Pixel Streaming.

**Pipeline:**
```
AI assets (T4a) → Unreal Engine scene → Pixel Streaming 2
  → Browser (WebXR) → Meta Quest / Vision Pro
```

**What exists today:**
- Pixel Streaming 2 plugin: official, supports Meta Quest 2/3 + Apple Vision Pro
- TensorWorks has resolved key VR controller input issues
- WebXR standard enables browser-based VR viewing
- HTTPS required for WebXR (self-signed cert works for local dev)

**Gap analysis:**
- **Unreal Engine not installed** — largest single gap. UE5 install is ~50-100 GB
- Pixel Streaming VR is still marked "experimental" by Epic
- Needs signaling server (included with UE, or use STUN server script)
- VRAM: Unreal rendering + Pixel Streaming encoding = 8-16 GB depending on scene complexity
- Cannot run Unreal + ComfyUI heavy inference simultaneously on single GPU

**Honest assessment:** Experimental. Requires Unreal Engine installation (major step). VR Pixel Streaming works but has rough edges. This is the highest-risk, highest-reward tier.

---

## Hardware Budget

| Component | VRAM | Can Coexist? |
|-----------|------|--------------|
| Ollama (mistral-nemo) | ~4 GB | Yes — always loaded |
| ComfyUI idle | ~2 GB | Yes |
| StreamDiffusion real-time (T3) | 4-6 GB | Yes with Ollama |
| ControlNet + StreamDiffusion (T3b) | 8-10 GB | Yes with Ollama |
| TripoSR (T4a) | 6-8 GB | Yes — batch, not persistent |
| TRELLIS.2 (T4a) | 12-24 GB | Load/unload per job |
| Unreal + Pixel Streaming (T4b) | 8-16 GB | **Cannot coexist with heavy ComfyUI** |
| **A6000 total** | **48 GB** | T3: comfortable. T4: sequential operations. |

**Key constraint:** T4b (Unreal rendering) and ComfyUI heavy inference cannot run simultaneously. Workflow: generate assets in ComfyUI → unload → launch Unreal scene → stream.

---

## Cost

| Item | Cost | Notes |
|------|------|-------|
| All local inference | $0 | TripoSR, StreamDiffusion, ControlNet — all open-source |
| Unreal Engine 5 | $0 | Free until $1M revenue |
| Live Link Face app | $0 | Free (iOS + Android) |
| Blender | $0 | Open source |
| ComfyUI + all nodes | $0 | Open source |
| Ollama models | $0 | Open weights |
| **Total additional cost** | **$0** | Everything runs on existing ENKI64 hardware |

Only potential cost: cloud GPU rental if VRAM becomes a bottleneck during demos (not expected with A6000 48 GB).

---

## Timeline

```
PREREQUISITE: T2 (YouTube Shorts) must PASS before any T3/T4 work begins.

Week 4 (Mar 24-28) — T3: AI Livestreaming
  Day 1-2: Install StreamDiffusion ComfyUI node, build webcam → style transfer workflow
  Day 3:   Test real-time frame rates, optimize latency (<100ms target)
  Day 4:   OBS integration, test actual stream output
  Day 5:   Buffer / polish. Live Link Face exploration if time.
  GATE:    Can we stream AI-styled video in real-time? YES/NO → proceed to T4 or stop.

Week 5 (Mar 31 - Apr 4) — T4a: 3D Asset Generation
  Day 1:   Install ComfyUI-3D-Pack + TripoSR. Test single-image → mesh.
  Day 2:   Blender MCP automated cleanup pipeline (UV unwrap, export glTF)
  Day 3:   Batch generation: ComfyUI textures → TripoSR meshes → Blender export
  Day 4-5: Install Unreal Engine if not already present. Import test assets.
  GATE:    Can we generate usable 3D assets from AI images? YES/NO.

Week 6 (Apr 7-11) — T4b: Virtual Set Streaming (if T4a passes)
  Day 1-2: Unreal scene setup with AI-generated assets
  Day 3:   Pixel Streaming 2 configuration + HTTPS/WebXR setup
  Day 4:   Test with Meta Quest / browser VR viewer
  Day 5:   Demo preparation
  GATE:    Can someone view an AI-populated VR scene in a browser? YES/NO.
```

**Honest timeline assessment:**
- T3b (style transfer stream) is achievable in 1 week — all components exist
- T4a (3D asset gen) is achievable but depends on model download speeds + Blender MCP reliability
- T4b (VR streaming) is ambitious — requires Unreal Engine installation and experimental features
- If T4b doesn't work in time, T4a assets can still be shown in Blender viewport as fallback

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Unreal Engine not installed (50-100 GB) | HIGH | Install during T4a prep. Worst case: show 3D assets in Blender, skip Pixel Streaming |
| StreamDiffusion latency >100ms | MEDIUM | SD-turbo + TensorRT acceleration. A6000 has headroom. Acceptable at 200ms for demo |
| VRAM contention (Unreal + ComfyUI) | MEDIUM | Sequential workflow: generate assets → unload ComfyUI → launch Unreal |
| Pixel Streaming VR still experimental | MEDIUM | Fallback: non-VR Pixel Streaming (browser 2D view) is stable and proven |
| Live Link Face → ComfyUI bridge doesn't exist | LOW | Skip iPhone path entirely. Use webcam + MediaPipe. Same demo value |
| UE 5.5 FBX/glTF reimport regressions | LOW | Use glTF 2.0 (recommended), avoid reimport (fresh import per iteration) |

---

## PLACEHOLDER: [Ari's framing and creative pitch angle]

Suggested talking points for Ari to customize:
- How AI-generated livestream visuals differentiate Agile Lens from competitors
- Connection to VR theater work (Christmas Carol as proof of concept)
- "Local inference = zero cloud costs" as selling point for budget-conscious clients
- Progressive complexity: each tier proves the next is worth attempting

## PLACEHOLDER: [Demo concept for Alex meeting]

Options to consider:
- Live webcam → Art Deco style transfer (most impressive, least risk)
- Single image → 3D mesh → Blender turntable render (proves asset pipeline)
- Side-by-side: raw footage vs AI-processed output (shows value prop)

## PLACEHOLDER: [Connection to Agile Lens client value prop]

Questions for Ari:
- Which Agile Lens clients would benefit from AI livestreaming?
- Is VR content creation a service AL wants to offer, or internal R&D only?
- Does Alex care more about the tech demo or the business case?
