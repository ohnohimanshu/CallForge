# FreePBX → CallForge: Method 1 Direct AudioSocket

**Recommended.** For conversational AI voice agents, latency and barge-in matter more than anything else. Direct AudioSocket is purpose-built for AI voice engines; a SIP trunk between FreePBX and CallForge adds unnecessary complexity and delay.

CallForge does **not** replace FreePBX. FreePBX keeps phones, trunks, IVRs, and queues. CallForge is the AI AudioSocket endpoint.

---

## Side-by-side comparison

| Feature | Method 1: Direct AudioSocket (recommended) | Method 2: SIP / PJSIP trunk |
|--------|--------------------------------------------|-----------------------------|
| Audio latency | Ultra-low (&lt;5ms) — raw PCM over TCP | Higher (+50–120ms) — SIP/SDP + RTP jitter buffers |
| Barge-in / interruption | Instant — clears the 20ms buffer when the caller speaks | Sluggish — buffered RTP often plays 0.5–1.5s after interrupt |
| Architecture | Single hop: FreePBX → CallForge Python AI | Double hop: FreePBX → SIP → CallForge Asterisk → AI |
| Codec / quality | Asterisk decodes to clean 8kHz/16-bit PCM | Codec alignment across two Asterisk instances |
| Firewall / NAT | 1 TCP port per agent (e.g. 9092) + API 8080 | 5060 UDP + wide RTP ranges (10000–20000) |
| Setup effort | Short dialplan in `extensions_custom.conf` + Custom Destination | Trunks, inbound/outbound routes, PJSIP credentials on both sides |

---

## Why AudioSocket wins

1. **Built for AI voice engines** — Asterisk `res_audiosocket` streams raw PCM into CallForge’s event loop; no SIP signaling stack in the AI path.
2. **No double-PBX penalty** — You are not chaining FreePBX Asterisk → CallForge Asterisk.
3. **Clean human handoff** — When CallForge detects escalation, it closes AudioSocket and FreePBX routes the *same* live channel to an extension or ring group.

Use Method 2 (SIP trunk) only if FreePBX is extremely old (Asterisk &lt; 16.14) without AudioSocket. Modern FreePBX 16/17 run Asterisk 18/20/21 with AudioSocket built in.

---

## Quick setup

### 1. Run CallForge (no embedded Asterisk required)

```bash
cp env.example .env
# Set the LAN IP FreePBX will use to reach this host:
# FREEPBX_AUDIOSOCKET_HOST=10.17.2.139
# FREEPBX_API_BASE=http://10.17.2.139:8080

docker compose up -d
```

Open `http://<callforge-ip>:8080` → deploy an agent (default agent uses TCP **9092**, extension hint **2000**).

### 2. Firewall

Allow FreePBX → CallForge:

- TCP **8080** — session register + handoff API  
- TCP **9092–9101** — AudioSocket PCM (one port per deployed agent)

### 3. FreePBX dialplan

In CallForge UI open **FreePBX / AudioSocket**, copy the dialplan, and append it to:

`/etc/asterisk/extensions_custom.conf`

Or fetch it:

```bash
curl -s http://<callforge-ip>:8080/api/telephony/freepbx/dialplan
```

Apply Config in FreePBX (or `asterisk -rx "dialplan reload"`).

### 4. Custom Destination + routing

1. **Admin → Custom Destinations** → add target: `callforge-agent-2000,s,1` (match your agent extension).
2. Point an **Inbound Route**, IVR option, or queue failover at that Custom Destination.
3. Place a test call.

### 5. Human handoff

Configure the agent’s handoff extension in CallForge (e.g. `101` or ring group `600`). After AudioSocket ends, FreePBX dialplan GETs `/api/telephony/handoff/<uuid>` and `Goto(from-internal,<target>,1)`.

---

## What CallForge no longer needs to do

| Old CallForge-as-PBX | FreePBX Method 1 |
|----------------------|------------------|
| Add/remove SIP phones in CallForge UI | Manage phones in FreePBX |
| Run embedded `asterisk-pbx` container | FreePBX is the PBX |
| Open SIP 5060 + RTP ranges on CallForge | Only AudioSocket TCP + HTTP API |
| SIP trunk CallForge ↔ FreePBX | Direct AudioSocket |

Optional lab Asterisk (not for FreePBX production):

```bash
docker compose --profile legacy-asterisk up -d
```

---

## Example dialplan fragment

```ini
[callforge-agent-2000]
exten => s,1,NoOp(CallForge Method 1 AudioSocket)
 same => n,Answer()
 same => n,Wait(0.2)
 same => n,Set(CALL_UUID=${SHELL(cat /proc/sys/kernel/random/uuid | tr -d '\n')})
 same => n,Set(CF_API=http://10.17.2.139:8080)
 same => n,Set(CF_REG=${CURL(${CF_API}/api/telephony/session?call_uuid=${CALL_UUID}&caller_id=${CALLERID(num)})})
 same => n,AudioSocket(${CALL_UUID},10.17.2.139:9092)
 same => n,Set(TARGET=${CURL(${CF_API}/api/telephony/handoff/${CALL_UUID})})
 same => n,GotoIf($["${TARGET}" != ""]?do_handoff:do_hangup)
 same => n(do_handoff),Goto(from-internal,${TARGET},1)
 same => n(do_hangup),Hangup()
```

Generated files also land at:

`platform_data/freepbx/extensions_custom_callforge.conf`
