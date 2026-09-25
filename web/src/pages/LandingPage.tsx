import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Activity,
  ArrowRight,
  Bot,
  Calendar,
  CheckCircle2,
  ChevronDown,
  CreditCard,
  Database,
  Headphones,
  Layers,
  Lock,
  Menu,
  MessageSquare,
  Pause,
  Phone,
  PhoneCall,
  PhoneOff,
  Play,
  Radio,
  Server,
  Shield,
  ShoppingCart,
  Sparkles,
  X,
  Zap,
} from 'lucide-react'
import Lenis from 'lenis'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useAuth } from '../auth'
import { AuthModal } from '../components/AuthModal'
import { useToast } from '../toast'
import '../landing.css'

gsap.registerPlugin(ScrollTrigger)

interface AgentScenario {
  id: string
  name: string
  icon: any
  iconColor: string
  category: string
  systemPrompt: string
  tools: string[]
  dialogue: {
    language: string
    speaker: 'agent' | 'caller'
    text: string
    sttMs: number
    llmMs: number
    ttsMs: number
  }[]
}

const AGENT_SCENARIOS: AgentScenario[] = [
  {
    id: 'cart-recovery',
    name: 'Cart Recovery Nudge',
    icon: ShoppingCart,
    iconColor: 'green',
    category: 'E-Commerce & Retail',
    systemPrompt:
      'You are Maya, an intelligent shopping assistant for NeoCart. The customer left a premium noise-canceling headset in their checkout basket 45 minutes ago. Inquire politely if they experienced payment issues and offer an instant 10% promotional code if they complete checkout now.',
    tools: ['Order_DB: #NC-8921', 'Coupon_Engine: SAVE10', 'SMS_Dispatch: UPI_Link'],
    dialogue: [
      {
        language: 'English',
        speaker: 'caller',
        text: 'Hello? Who is this?',
        sttMs: 180,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Hi Priya! This is Maya from NeoCart. I noticed you were looking at the Sony WH-1000XM5 headphones earlier. Did you run into any trouble during checkout?',
        sttMs: 190,
        llmMs: 95,
        ttsMs: 70,
      },
      {
        language: 'English',
        speaker: 'caller',
        text: 'Oh, hey Maya. The price was just a little steep for my budget today.',
        sttMs: 210,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'I completely understand! As a weekend special, I can apply a direct 10% credit discount right now, bringing it down to $269. Shall I send a one-tap secure link to your WhatsApp?',
        sttMs: 200,
        llmMs: 110,
        ttsMs: 65,
      },
    ],
  },
  {
    id: 'inbound-support',
    name: 'Inbound Support & Dispute',
    icon: CreditCard,
    iconColor: 'indigo',
    category: 'Fintech & Banking',
    systemPrompt:
      'You are Arjun, Tier-1 customer banking specialist for Apex Trust Bank. Verify caller ID, query recent transactions, and handle lost card freezes or suspicious charge disputes securely.',
    tools: ['Core_Banking: API_v3', 'Card_Lock: InstFreeze', 'Fraud_Scorer: SubSecond'],
    dialogue: [
      {
        language: 'English',
        speaker: 'caller',
        text: 'Hi, I just got an SMS about an unrecognized debit of 4,200 rupees from my savings account.',
        sttMs: 220,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'I can help you right away, Rohan. I see a pending POS authorization from an international merchant 4 minutes ago. For your protection, should I temporarily lock your debit card right now?',
        sttMs: 185,
        llmMs: 105,
        ttsMs: 75,
      },
      {
        language: 'English',
        speaker: 'caller',
        text: 'Yes please, lock it immediately! What about my money?',
        sttMs: 195,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Your card ending in 8192 is now locked. No further funds can leave. I have opened Fraud Ticket #F-4910 and triggered a reversal review. You will receive an SMS confirmation in 30 seconds.',
        sttMs: 190,
        llmMs: 98,
        ttsMs: 62,
      },
    ],
  },
  {
    id: 'lead-qualification',
    name: 'B2B Lead Qualification',
    icon: Sparkles,
    iconColor: 'orange',
    category: 'Enterprise SaaS',
    systemPrompt:
      'You are Elena from CallForge SDR. Qualify enterprise prospects inquiring about VoIP PBX AI agents. Check their monthly call volume, telephony provider (Asterisk/Twilio/SIP), and schedule an executive demo with solution engineers.',
    tools: ['HubSpot_CRM: AutoSync', 'Cal_com: InstantBook', 'SIP_Detect: PJSIP_Trunk'],
    dialogue: [
      {
        language: 'English',
        speaker: 'caller',
        text: 'Hi, we are running 40 customer support agents on Asterisk PBX and exploring AI agents.',
        sttMs: 210,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Welcome! CallForge connects directly into Asterisk via AudioSocket TCP at 8kHz PCM, meaning zero transcoding latency. Roughly how many concurrent inbound lines do you maintain at peak?',
        sttMs: 195,
        llmMs: 112,
        ttsMs: 68,
      },
      {
        language: 'English',
        speaker: 'caller',
        text: 'We peak at around 80 concurrent channels between 2 PM and 6 PM.',
        sttMs: 180,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'That fits comfortably on a single CallForge cluster node. Would tomorrow at 3:30 PM work for a live 15-minute softphone test with our telephony architect?',
        sttMs: 190,
        llmMs: 104,
        ttsMs: 72,
      },
    ],
  },
  {
    id: 'payment-collections',
    name: 'Payment & Collections',
    icon: ShoppingCart,
    iconColor: 'blue',
    category: 'NBFC & Lending',
    systemPrompt:
      'You are Aditi, polite accounts assistant for ZenLoan. Remind borrower of their upcoming micro-loan EMI due date and offer instant UPI Autopay setup or flexible 3-day extension if requested.',
    tools: ['Loan_Ledger: EMI_Status', 'UPI_Collect: RazorpayIntent', 'Schedule_Followup: CRM'],
    dialogue: [
      {
        language: 'English',
        speaker: 'caller',
        text: 'Hello, I received a missed call from this number.',
        sttMs: 180,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Namaste Vikram ji. This is Aditi from ZenLoan. I am calling to assist with your monthly EMI of 3,450 rupees due tomorrow. Would you like me to send a quick UPI payment link to your registered phone?',
        sttMs: 190,
        llmMs: 96,
        ttsMs: 64,
      },
      {
        language: 'English',
        speaker: 'caller',
        text: 'Can I pay on Friday when my salary credits?',
        sttMs: 175,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Certainly! I have updated your due date to Friday, October 24th with zero late fee penalty. You will receive an updated schedule via WhatsApp shortly. Have a wonderful day!',
        sttMs: 185,
        llmMs: 102,
        ttsMs: 65,
      },
    ],
  },
  {
    id: 'clinic-booking',
    name: 'Clinic Appointment Booking',
    icon: Calendar,
    iconColor: 'rose',
    category: 'Healthcare & Wellness',
    systemPrompt:
      'You are Priya, front-desk concierge for Apollo Care. Help patients schedule clinic consultations with specialized doctors, verify insurance, and send calendar invites with directions.',
    tools: ['EHR_Database: Dr_Slots', 'Google_Cal: SyncEvent', 'WhatsApp_Bot: Directions'],
    dialogue: [
      {
        language: 'English',
        speaker: 'caller',
        text: 'Hi, does Dr. Mehta have an opening for a cardiology follow-up this week?',
        sttMs: 200,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'Hello! Yes, Dr. Mehta has two consultations available: Thursday at 4:00 PM or Friday at 11:30 AM. Which one fits your schedule better?',
        sttMs: 190,
        llmMs: 98,
        ttsMs: 70,
      },
      {
        language: 'English',
        speaker: 'caller',
        text: 'Thursday at 4:00 PM is perfect.',
        sttMs: 160,
        llmMs: 0,
        ttsMs: 0,
      },
      {
        language: 'English',
        speaker: 'agent',
        text: 'You are booked for Thursday at 4:00 PM at Apollo Clinic Suite 402. I have sent the calendar invite and digital registration form to your mobile. See you on Thursday!',
        sttMs: 175,
        llmMs: 105,
        ttsMs: 68,
      },
    ],
  },
]

const AUDIO_SHOWCASES = [
  {
    id: 'audio-hindi',
    language: 'Hindi (हिंदी)',
    langCode: 'hi-IN',
    agent: 'Aditi Sharma',
    role: 'Sales Recovery Specialist',
    scenario: 'E-commerce cart recovery with native Hindi conversational nuance',
    duration: '0:28',
    latency: '372ms',
    transcript: 'नमस्ते राहुल जी! नियोकार्ट से अदिति बात कर रही हूँ। आपके कार्ट में एक स्मार्टवॉच बची हुई है, क्या मैं आपके लिए विशेष 10% छूट लागू कर दूँ?',
    badgeColor: '#ea580c',
    badgeBg: '#fff7ed',
    gender: 'female' as const,
    pitch: 1.15,
    rate: 0.92,
    preferredVoices: ['Google हिन्दी', 'Lekha', 'Kalpana', 'hi-IN', 'hi', 'India', 'Hindi'],
    vocalProfile: 'audio-hindi',
  },
  {
    id: 'audio-english',
    language: 'English (US/Global)',
    langCode: 'en-US',
    agent: 'Marcus Vance',
    role: 'DevOps & Telephony Lead',
    scenario: 'VoIP SIP trunk diagnostic and real-time Asterisk packet analysis',
    duration: '0:34',
    latency: '364ms',
    transcript: 'Good morning. I see your PJSIP endpoint re-registered with 8kHz linear PCM over port 9092. The NAT keep-alive is active with sub-390ms latency.',
    badgeColor: '#2563eb',
    badgeBg: '#eff6ff',
    gender: 'male' as const,
    pitch: 0.78,
    rate: 0.98,
    preferredVoices: ['Google US English', 'Daniel', 'David', 'Alex', 'Mark', 'en-US', 'Male'],
    vocalProfile: 'audio-english',
  },
  {
    id: 'audio-hinglish',
    language: 'Hinglish (Code-Switch)',
    langCode: 'en-IN',
    agent: 'Elena Roy',
    role: 'VIP Concierge Executive',
    scenario: 'Luxury hotel booking confirmation with fluid Hindi-English code-switching',
    duration: '0:31',
    latency: '388ms',
    transcript: 'Haan bilkul sir, aapka Executive Suite confirm ho gaya hai with complimentary breakfast and valet parking. WhatsApp par receipt bhej di hai!',
    badgeColor: '#7c3aed',
    badgeBg: '#f5f3ff',
    gender: 'female' as const,
    pitch: 1.22,
    rate: 1.05,
    preferredVoices: ['Google English (India)', 'Rishi', 'Neerja', 'en-IN', 'hi-IN', 'India'],
    vocalProfile: 'audio-hinglish',
  },
  {
    id: 'audio-tamil',
    language: 'Tamil (தமிழ்)',
    langCode: 'ta-IN',
    agent: 'Kavitha Raman',
    role: 'Logistics Dispatch Lead',
    scenario: 'Express delivery reschedule and pin-point address confirmation',
    duration: '0:26',
    latency: '379ms',
    transcript: 'வணக்கம், உங்கள் பார்சல் இன்று மாலை 4 மணிக்கு டெலிவரி செய்யப்படும். நீங்கள் வீட்டில் இருப்பீர்களா அல்லது நேரத்தை மாற்றவா?',
    badgeColor: '#059669',
    badgeBg: '#ecfdf5',
    gender: 'female' as const,
    pitch: 0.96,
    rate: 0.88,
    preferredVoices: ['Google தமிழ்', 'Valluvar', 'ta-IN', 'ta', 'Tamil'],
    vocalProfile: 'audio-tamil',
  },
]

const FAQS = [
  {
    question: "What is CallForge's Voice Agents Platform?",
    answer:
      'CallForge is an enterprise conversational AI voice runtime engineered specifically for sub-second, human-sounding voice conversations over telephone lines (SIP/PSTN) and WebRTC. Unlike standard chatbots with text-to-speech bolted on, CallForge integrates an ultra-low latency pipeline (Silero VAD + streaming LLM reasoning + neural speech synthesis) directly into Asterisk PBX via high-speed AudioSocket TCP.',
  },
  {
    question: 'How quickly can I deploy an agent?',
    answer:
      'You can launch your first production-ready voice agent in minutes. You simply define the persona instructions, attach any custom REST tools or CRM databases, select a voice, and assign an Asterisk dialplan extension (e.g. ext 1001). You can test it immediately in your browser via our live simulator or dial into it from any SIP softphone.',
  },
  {
    question: 'What languages and accents does it support?',
    answer:
      'CallForge supports 12+ Indian and global languages, including Hindi, English, Hinglish (code-switching), Tamil, Telugu, Kannada, Marathi, Bengali, Gujarati, Spanish, and German. Our acoustic models are trained on real-world telephony audio (G.711u / 8kHz linear PCM) so conversations remain crisp even over mobile networks.',
  },
  {
    question: 'Can I integrate with my existing telephony and CRMs?',
    answer:
      'Yes, absolutely. CallForge provides native Asterisk PJSIP integration, Twilio Elastic SIP Trunking, Exotel, and standard RFC 3261 SIP bridges. It also includes bidirectional function calling mid-conversation to query Salesforce, HubSpot, PostgreSQL, payment gateways, and custom internal APIs.',
  },
  {
    question: 'How does sub-20ms barge-in and latency turnaround work?',
    answer:
      'CallForge utilizes an edge-optimized Silero VAD (Voice Activity Detection) running on raw 8kHz PCM chunks. The instant caller speech energy is detected, the audio bridge halts speech playback in under 20ms and triggers a cancel frame to the streaming LLM, preventing frustrating agent monologue interruptions.',
  },
  {
    question: 'What kind of analytics and evaluations do I get?',
    answer:
      'Every call generates an automated post-call evaluation, including full verbatim transcripts, speaker diarization, latency waterfall breakdowns (STT, LLM time-to-first-token, TTS synthesis), customer sentiment trajectory, and structured JSON summaries that push directly to your data warehouse.',
  },
]

// --------------------------------------------------------------------------
// MULTI-VOICE SPEECH & ACOUSTIC FORMANT SYNTHESIS ENGINE
// --------------------------------------------------------------------------

// Find best matching voice from available system voices
function getVoiceForAgent(
  langCode: string,
  gender: 'male' | 'female',
  preferredNames: string[] = []
): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null
  const voices = window.speechSynthesis.getVoices()
  if (!voices || voices.length === 0) return null

  // 1. Try preferred voice names
  for (const name of preferredNames) {
    const match = voices.find((v) => v.name.toLowerCase().includes(name.toLowerCase()))
    if (match) return match
  }

  // 2. Try exact language prefix (e.g. 'hi-IN', 'ta-IN', 'en-US')
  const langMatches = voices.filter((v) => {
    const vLang = v.lang.toLowerCase().replace('_', '-')
    return vLang.startsWith(langCode.toLowerCase()) || vLang.includes(langCode.toLowerCase())
  })

  if (langMatches.length > 0) {
    if (gender === 'male') {
      const maleMatch = langMatches.find((v) => /male|david|daniel|rishi|george|alex|hemant/i.test(v.name))
      if (maleMatch) return maleMatch
    } else {
      const femaleMatch = langMatches.find((v) => /female|zira|samantha|aditi|kavitha|lekha|kalpana|victoria|karen/i.test(v.name))
      if (femaleMatch) return femaleMatch
    }
    return langMatches[0]
  }

  // 3. Indian language fallback (e.g. en-IN or hi-IN)
  if (langCode.startsWith('hi') || langCode.startsWith('ta')) {
    const inMatch = voices.find((v) => v.lang.toLowerCase().includes('in'))
    if (inMatch) return inMatch
  }

  // 4. Fallback by gender
  if (gender === 'male') {
    const maleVoice = voices.find((v) => /male|david|daniel|george|alex|mark|guy/i.test(v.name))
    if (maleVoice) return maleVoice
  } else {
    const femaleVoice = voices.find((v) => /female|zira|samantha|karen|victoria|susan/i.test(v.name))
    if (femaleVoice) return femaleVoice
  }

  return voices[0] || null
}

// Infallible Web Audio Formant Synthesizer generating 4 radically distinct voices
function playVocalFormantSynthesizer(
  profileId: string,
  durationSec: number,
  onProgress: (pct: number) => void,
  onEnd: () => void
): () => void {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioCtx) {
      onEnd()
      return () => {}
    }
    const ctx = new AudioCtx()
    let isCancelled = false
    let timerId: ReturnType<typeof setTimeout> | null = null

    interface FormantProfile {
      baseFreq: number
      f1: number
      f2: number
      f3: number
      vowelFreqs: number[]
      cadenceMs: number
      vibratoRate: number
      vibratoDepth: number
    }

    const profiles: Record<string, FormantProfile> = {
      'audio-hindi': {
        baseFreq: 245, // Soft polite Hindi female soprano
        f1: 530,
        f2: 1840,
        f3: 2800,
        vowelFreqs: [245, 275, 290, 245, 260, 290, 310, 245, 265, 280],
        cadenceMs: 220,
        vibratoRate: 5.5,
        vibratoDepth: 3.5,
      },
      'audio-english': {
        baseFreq: 112, // Deep authoritative US male baritone
        f1: 380,
        f2: 1200,
        f3: 2400,
        vowelFreqs: [112, 118, 125, 112, 108, 115, 112, 105, 110, 114],
        cadenceMs: 290,
        vibratoRate: 4.0,
        vibratoDepth: 1.5,
      },
      'audio-hinglish': {
        baseFreq: 228, // Bright energetic Hinglish concierge alto
        f1: 640,
        f2: 1920,
        f3: 2900,
        vowelFreqs: [228, 255, 280, 240, 265, 285, 300, 235, 250, 275],
        cadenceMs: 195,
        vibratoRate: 6.0,
        vibratoDepth: 3.8,
      },
      'audio-tamil': {
        baseFreq: 202, // Grounded rhythmic Tamil female dispatch
        f1: 460,
        f2: 1680,
        f3: 2600,
        vowelFreqs: [202, 215, 228, 202, 210, 225, 205, 195, 212, 220],
        cadenceMs: 240,
        vibratoRate: 4.8,
        vibratoDepth: 2.5,
      },
    }

    const profile = profiles[profileId] || profiles['audio-english']
    const totalSteps = Math.floor((durationSec * 1000) / profile.cadenceMs)
    let step = 0

    const playVocalUnit = () => {
      if (isCancelled || ctx.state === 'closed') return
      const now = ctx.currentTime

      const osc = ctx.createOscillator()
      osc.type = 'sawtooth'
      const baseNote = profile.vowelFreqs[step % profile.vowelFreqs.length]
      osc.frequency.setValueAtTime(baseNote, now)

      // Vibrato LFO
      const lfo = ctx.createOscillator()
      const lfoGain = ctx.createGain()
      lfo.frequency.setValueAtTime(profile.vibratoRate, now)
      lfoGain.gain.setValueAtTime(profile.vibratoDepth, now)
      lfo.connect(osc.frequency)
      lfo.start(now)
      lfo.stop(now + (profile.cadenceMs / 1000) * 0.9)

      // Vocal Tract Formant Filters
      const f1 = ctx.createBiquadFilter()
      f1.type = 'bandpass'
      f1.frequency.setValueAtTime(profile.f1, now)
      f1.Q.setValueAtTime(6.0, now)

      const f2 = ctx.createBiquadFilter()
      f2.type = 'bandpass'
      f2.frequency.setValueAtTime(profile.f2, now)
      f2.Q.setValueAtTime(7.0, now)

      const f3 = ctx.createBiquadFilter()
      f3.type = 'bandpass'
      f3.frequency.setValueAtTime(profile.f3, now)
      f3.Q.setValueAtTime(8.0, now)

      const vocalGain = ctx.createGain()
      const unitDuration = (profile.cadenceMs / 1000) * 0.88
      vocalGain.gain.setValueAtTime(0.001, now)
      vocalGain.gain.linearRampToValueAtTime(0.07, now + 0.04)
      vocalGain.gain.exponentialRampToValueAtTime(0.001, now + unitDuration)

      osc.connect(f1)
      osc.connect(f2)
      osc.connect(f3)

      f1.connect(vocalGain)
      f2.connect(vocalGain)
      f3.connect(vocalGain)
      vocalGain.connect(ctx.destination)

      osc.start(now)
      osc.stop(now + unitDuration)

      step++
      const pct = Math.min(100, Math.round((step / totalSteps) * 100))
      onProgress(pct)

      if (step < totalSteps && !isCancelled) {
        timerId = setTimeout(playVocalUnit, profile.cadenceMs)
      } else if (!isCancelled) {
        onProgress(100)
        onEnd()
      }
    }

    if (ctx.state === 'suspended') {
      ctx.resume().then(playVocalUnit)
    } else {
      playVocalUnit()
    }

    return () => {
      isCancelled = true
      if (timerId) clearTimeout(timerId)
      try {
        ctx.close()
      } catch {}
    }
  } catch {
    onEnd()
    return () => {}
  }
}

// Master voice player for Audio Showcase with distinct voices
function playAudioShowcaseVoice(
  sample: (typeof AUDIO_SHOWCASES)[number],
  onProgress: (pct: number) => void,
  onEnd: () => void
): () => void {
  let isCancelled = false

  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    try {
      window.speechSynthesis.cancel()

      const utter = new SpeechSynthesisUtterance(sample.transcript)
      utter.lang = sample.langCode
      utter.pitch = sample.pitch
      utter.rate = sample.rate

      const matchedVoice = getVoiceForAgent(sample.langCode, sample.gender, sample.preferredVoices)
      if (matchedVoice) {
        utter.voice = matchedVoice
      }

      const totalChars = sample.transcript.length
      utter.onboundary = (e) => {
        if (isCancelled) return
        if (e.charIndex !== undefined && totalChars > 0) {
          const pct = Math.min(95, Math.round((e.charIndex / totalChars) * 100))
          onProgress(pct)
        }
      }

      utter.onend = () => {
        if (!isCancelled) {
          onProgress(100)
          onEnd()
        }
      }

      utter.onerror = () => {
        if (!isCancelled) {
          playVocalFormantSynthesizer(sample.id, 6.5, onProgress, onEnd)
        }
      }

      window.speechSynthesis.speak(utter)

      return () => {
        isCancelled = true
        try {
          window.speechSynthesis.cancel()
        } catch {}
      }
    } catch {
      // Fallback below
    }
  }

  // Fallback to distinct formant synthesis
  return playVocalFormantSynthesizer(sample.id, 6.5, onProgress, onEnd)
}

// Telephony chime helper for live call sandbox (Dial ring, barge cutoff, hangup)
function playCallChime(type: 'ring' | 'barge' | 'hangup') {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    const now = ctx.currentTime

    if (type === 'ring') {
      const osc1 = ctx.createOscillator()
      const osc2 = ctx.createOscillator()
      const gain = ctx.createGain()
      osc1.frequency.setValueAtTime(440, now)
      osc2.frequency.setValueAtTime(480, now)
      gain.gain.setValueAtTime(0.045, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38)
      osc1.connect(gain)
      osc2.connect(gain)
      gain.connect(ctx.destination)
      osc1.start(now)
      osc2.start(now)
      osc1.stop(now + 0.38)
      osc2.stop(now + 0.38)
    } else if (type === 'barge') {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sawtooth'
      osc.frequency.setValueAtTime(880, now)
      osc.frequency.exponentialRampToValueAtTime(180, now + 0.12)
      gain.gain.setValueAtTime(0.06, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.12)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now)
      osc.stop(now + 0.12)
    } else {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.setValueAtTime(360, now)
      osc.frequency.exponentialRampToValueAtTime(140, now + 0.25)
      gain.gain.setValueAtTime(0.04, now)
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(now)
      osc.stop(now + 0.25)
    }
  } catch {}
}

export function LandingPage() {
  const { user } = useAuth()
  const { show } = useToast()
  const navigate = useNavigate()

  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('signup')

  // Interactive Stepper State
  const [activeStep, setActiveStep] = useState<number>(0)
  const steps = [
    { title: 'Describe', icon: MessageSquare, desc: 'Write instructions and connect tools' },
    { title: 'Test', icon: Phone, desc: 'Live browser sandbox with sub-second turnaround' },
    { title: 'Get a number', icon: Radio, desc: 'Assign a SIP trunk or Asterisk PBX extension' },
    { title: 'Go live', icon: Sparkles, desc: 'Handle 10,000+ concurrent carrier calls' },
  ]

  // Interactive 3-Column Studio State
  const [selectedAgent, setSelectedAgent] = useState<AgentScenario>(AGENT_SCENARIOS[0])
  const [activeLanguage, setActiveLanguage] = useState<string>('English')
  const [isCallActive, setIsCallActive] = useState<boolean>(false)
  const [activeCallTurn, setActiveCallTurn] = useState<number>(-1)
  const [isAgentSpeaking, setIsAgentSpeaking] = useState<boolean>(false)
  const [isBargedIn, setIsBargedIn] = useState<boolean>(false)
  const [callDuration, setCallDuration] = useState<number>(0)
  const [chatTranscript, setChatTranscript] = useState(selectedAgent.dialogue)
  const [telemetryLatency, setTelemetryLatency] = useState<number>(384)
  const [telemetryJitter, setTelemetryJitter] = useState<number>(1.2)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const callTurnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Audio Showcase State & Visualizer
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null)
  const [playbackProgress, setPlaybackProgress] = useState<number>(0)
  const [waveHeights, setWaveHeights] = useState<number[]>([
    12, 20, 15, 24, 18, 10, 22, 16, 26, 14, 19, 23, 11, 25, 17, 21, 14, 22, 18, 12,
  ])
  const audioCleanupRef = useRef<(() => void) | null>(null)

  // FAQ Accordion State
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0)

  // Fixed Navbar, Reading Progress & Lenis Scroll State
  const [isScrolled, setIsScrolled] = useState<boolean>(false)
  const [scrollProgress, setScrollProgress] = useState<number>(0)
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false)
  const [activeNav, setActiveNav] = useState<string>('live-demo')
  const lenisRef = useRef<Lenis | null>(null)

  // Section Refs for GSAP ScrollTrigger & Scroll Animations
  const heroRef = useRef<HTMLElement | null>(null)
  const stepperRef = useRef<HTMLDivElement | null>(null)
  const showcaseRef = useRef<HTMLDivElement | null>(null)
  const studioRef = useRef<HTMLElement | null>(null)
  const volumeRef = useRef<HTMLElement | null>(null)
  const featuresRef = useRef<HTMLElement | null>(null)
  const telephonyRef = useRef<HTMLElement | null>(null)
  const audioRef = useRef<HTMLElement | null>(null)
  const securityRef = useRef<HTMLElement | null>(null)
  const faqRef = useRef<HTMLElement | null>(null)
  const ctaRef = useRef<HTMLElement | null>(null)

  // Animated Telephony Volume Metrics
  const [metricCounts, setMetricCounts] = useState({
    minutes: '0.0M',
    latency: '800ms',
    uptime: '95.00%',
    lines: '0',
  })

  // Prime speech synthesis voices on mount
  useEffect(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      const load = () => {
        window.speechSynthesis.getVoices()
      }
      load()
      window.speechSynthesis.addEventListener('voiceschanged', load)
      return () => {
        window.speechSynthesis.removeEventListener('voiceschanged', load)
      }
    }
  }, [])

  // When selected agent changes, sync dialogue and reset call
  useEffect(() => {
    if (callTurnTimerRef.current) {
      clearTimeout(callTurnTimerRef.current)
      callTurnTimerRef.current = null
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }
    setChatTranscript(selectedAgent.dialogue)
    setIsCallActive(false)
    setActiveCallTurn(-1)
    setIsAgentSpeaking(false)
    setIsBargedIn(false)
    setCallDuration(0)
  }, [selectedAgent])

  // Call timer effect
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>
    if (isCallActive) {
      interval = setInterval(() => {
        setCallDuration((prev) => prev + 1)
      }, 1000)
    } else {
      setCallDuration(0)
    }
    return () => clearInterval(interval)
  }, [isCallActive])

  // Telemetry fluctuation during live call
  useEffect(() => {
    let timer: ReturnType<typeof setInterval>
    if (isCallActive) {
      timer = setInterval(() => {
        setTelemetryLatency(376 + Math.floor(Math.random() * 14))
        setTelemetryJitter(+(1.1 + Math.random() * 0.3).toFixed(1))
      }, 1400)
    } else {
      setTelemetryLatency(384)
      setTelemetryJitter(1.2)
    }
    return () => clearInterval(timer)
  }, [isCallActive])

  // Real-time Waveform Canvas Loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let phase = 0

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const w = canvas.width
      const h = canvas.height
      const mid = h / 2

      // Draw subtle background grid
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, mid)
      ctx.lineTo(w, mid)
      ctx.stroke()

      const isLive = isCallActive || playingAudioId !== null
      const bars = 48
      const barWidth = w / bars

      for (let i = 0; i < bars; i++) {
        let amplitude = 4
        if (isLive) {
          const sine = Math.sin(i * 0.28 + phase) * Math.cos(i * 0.15 - phase * 0.8)
          amplitude = Math.max(6, Math.abs(sine) * (isAgentSpeaking ? 28 : 14))
        }

        const x = i * barWidth + barWidth * 0.2
        const barH = amplitude * 2
        const y = mid - amplitude

        const grad = ctx.createLinearGradient(0, y, 0, y + barH)
        if (isAgentSpeaking) {
          grad.addColorStop(0, '#34d399')
          grad.addColorStop(1, '#059669')
        } else if (isLive) {
          grad.addColorStop(0, '#818cf8')
          grad.addColorStop(1, '#4f46e5')
        } else {
          grad.addColorStop(0, '#475569')
          grad.addColorStop(1, '#334155')
        }

        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.roundRect(x, y, barWidth * 0.6, barH, 2)
        ctx.fill()
      }

      phase += 0.08
      animationId = requestAnimationFrame(render)
    }

    render()
    return () => cancelAnimationFrame(animationId)
  }, [isCallActive, isAgentSpeaking, playingAudioId])

  // --------------------------------------------------------------------------
  // LIVE CALL TURN-BY-TURN SPEECH ORCHESTRATION
  // --------------------------------------------------------------------------
  const speakLiveTurn = (turnIndex: number) => {
    if (turnIndex >= selectedAgent.dialogue.length) {
      setIsAgentSpeaking(false)
      show(`✨ Call completed successfully with ${selectedAgent.name}.`)
      return
    }

    setActiveCallTurn(turnIndex)
    const item = selectedAgent.dialogue[turnIndex]
    const isAgent = item.speaker === 'agent'
    setIsAgentSpeaking(isAgent)

    // Agent persona voice settings
    let lang = 'en-US'
    let gender: 'male' | 'female' = 'female'
    let pitch = 1.05
    let rate = 1.0

    if (isAgent) {
      if (selectedAgent.id === 'inbound-support') {
        gender = 'male'
        pitch = 0.85
        rate = 0.98
      } else if (selectedAgent.id === 'cart-recovery') {
        gender = 'female'
        pitch = 1.15
        rate = 1.02
      } else if (selectedAgent.id === 'payment-collections') {
        gender = 'female'
        pitch = 1.05
        rate = 0.96
      } else {
        gender = 'female'
        pitch = 1.1
        rate = 1.0
      }
    } else {
      gender = selectedAgent.id === 'payment-collections' ? 'male' : 'female'
      pitch = gender === 'male' ? 0.92 : 1.05
      rate = 1.0
    }

    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
        const utter = new SpeechSynthesisUtterance(item.text)
        utter.lang = lang
        utter.pitch = pitch
        utter.rate = rate
        const voice = getVoiceForAgent(lang, gender)
        if (voice) utter.voice = voice

        utter.onend = () => {
          setIsAgentSpeaking(false)
          // Advance to next turn after realistic conversational pause
          callTurnTimerRef.current = setTimeout(() => {
            speakLiveTurn(turnIndex + 1)
          }, 850)
        }

        utter.onerror = () => {
          setIsAgentSpeaking(false)
          callTurnTimerRef.current = setTimeout(() => {
            speakLiveTurn(turnIndex + 1)
          }, 1200)
        }

        window.speechSynthesis.speak(utter)
        return
      } catch (err) {
        console.warn('SpeechSynthesis error:', err)
      }
    }

    // Fallback timer if speech synthesis is not active
    callTurnTimerRef.current = setTimeout(() => {
      setIsAgentSpeaking(false)
      callTurnTimerRef.current = setTimeout(() => {
        speakLiveTurn(turnIndex + 1)
      }, 750)
    }, 2800)
  }

  // Call toggle action (Start live call / End live call)
  const handleToggleCall = () => {
    if (!isCallActive) {
      setIsCallActive(true)
      setIsBargedIn(false)
      setCallDuration(0)
      playCallChime('ring')
      show(`📞 Connecting to ${selectedAgent.name} (Asterisk PJSIP :9092)...`)

      // Ring chime then start Turn 0
      callTurnTimerRef.current = setTimeout(() => {
        show(`✓ Call connected to ${selectedAgent.name}.`)
        speakLiveTurn(0)
      }, 850)
    } else {
      if (callTurnTimerRef.current) {
        clearTimeout(callTurnTimerRef.current)
        callTurnTimerRef.current = null
      }
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        try {
          window.speechSynthesis.cancel()
        } catch {}
      }
      setIsCallActive(false)
      setIsAgentSpeaking(false)
      setIsBargedIn(false)
      setActiveCallTurn(-1)
      playCallChime('hangup')
      show('Call ended.')
    }
  }

  // Barge-in interruption action (Instant sub-20ms speech cancellation)
  const handleBargeIn = () => {
    if (!isCallActive) {
      handleToggleCall()
      return
    }

    // Cut off speech synthesis immediately
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }
    if (callTurnTimerRef.current) {
      clearTimeout(callTurnTimerRef.current)
      callTurnTimerRef.current = null
    }

    setIsAgentSpeaking(false)
    setIsBargedIn(true)
    playCallChime('barge')
    show('⚡ User interrupted agent! Silero VAD stopped synthesis in 18ms.')

    // Resume conversation after brief caller intervention
    callTurnTimerRef.current = setTimeout(() => {
      setIsBargedIn(false)
      const nextTurn = activeCallTurn >= 0 ? activeCallTurn + 1 : 1
      if (nextTurn < selectedAgent.dialogue.length) {
        speakLiveTurn(nextTurn)
      }
    }, 1800)
  }

  // Advance or jump to next turn manually
  const handleNextTurn = () => {
    if (!isCallActive) {
      handleToggleCall()
      return
    }
    if (callTurnTimerRef.current) {
      clearTimeout(callTurnTimerRef.current)
      callTurnTimerRef.current = null
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }
    const next = (activeCallTurn + 1) % selectedAgent.dialogue.length
    speakLiveTurn(next)
  }

  // Handle Audio Showcase Toggle with distinct voices for each persona
  const handleToggleAudio = (id: string) => {
    // If playing, stop
    if (audioCleanupRef.current) {
      audioCleanupRef.current()
      audioCleanupRef.current = null
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {}
    }

    if (playingAudioId === id) {
      setPlayingAudioId(null)
      setPlaybackProgress(0)
    } else {
      const sample = AUDIO_SHOWCASES.find((s) => s.id === id)
      if (!sample) return

      setPlayingAudioId(id)
      setPlaybackProgress(0)
      show(`Playing voice: ${sample.agent} (${sample.language})...`)

      // Interval to dynamically bounce wave visualizer bars
      const waveInterval = setInterval(() => {
        setWaveHeights((prev) =>
          prev.map(() => Math.floor(Math.random() * 22) + 6)
        )
      }, 110)

      const stopFn = playAudioShowcaseVoice(
        sample,
        (pct) => {
          setPlaybackProgress(pct)
        },
        () => {
          clearInterval(waveInterval)
          setPlayingAudioId(null)
          setPlaybackProgress(0)
        }
      )

      audioCleanupRef.current = () => {
        clearInterval(waveInterval)
        stopFn()
      }
    }
  }

  // --------------------------------------------------------------------------
  // GSAP SCROLLTRIGGER, STAGGER ANIMATIONS & LENIS SMOOTH SCROLLING
  // --------------------------------------------------------------------------
  useEffect(() => {
    // 1. Initialize Lenis for Smooth Inertial Scrolling
    const lenis = new Lenis({
      duration: 1.15,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      orientation: 'vertical',
      gestureOrientation: 'vertical',
      smoothWheel: true,
      wheelMultiplier: 1.05,
      touchMultiplier: 1.8,
    })
    lenisRef.current = lenis

    const updateScrollTrigger = () => {
      ScrollTrigger.update()
    }
    lenis.on('scroll', updateScrollTrigger)

    const tickerCb = (time: number) => {
      lenis.raf(time * 1000)
    }
    gsap.ticker.add(tickerCb)
    gsap.ticker.lagSmoothing(0)

    // 2. Window scroll listener for dynamic navbar & reading progress
    const handleWindowScroll = () => {
      const scrollY = window.scrollY
      setIsScrolled(scrollY > 20)
      const docHeight = document.documentElement.scrollHeight - window.innerHeight
      if (docHeight > 0) {
        setScrollProgress(Math.min(100, Math.max(0, (scrollY / docHeight) * 100)))
      }
    }
    window.addEventListener('scroll', handleWindowScroll, { passive: true })

    // 3. GSAP Timelines and ScrollTriggers Scoped Context
    const ctx = gsap.context(() => {
      // Hero Entrance Timeline
      const heroTl = gsap.timeline({ defaults: { ease: 'power3.out' } })
      heroTl
        .from('.sarvam-micro-tag', { opacity: 0, y: -20, duration: 0.6, clearProps: 'opacity,transform' })
        .from('.sarvam-hero-title', { opacity: 0, y: 35, duration: 0.8, clearProps: 'opacity,transform' }, '-=0.35')
        .from('.sarvam-hero-subtitle', { opacity: 0, y: 22, duration: 0.7, clearProps: 'opacity,transform' }, '-=0.45')
        .from('.sarvam-hero-ctas', { opacity: 0, y: 18, duration: 0.6, clearProps: 'opacity,transform' }, '-=0.35')
        .from('.sarvam-hero-microcopy', { opacity: 0, duration: 0.5, clearProps: 'opacity,transform' }, '-=0.25')
        .from('.sarvam-stepper-pill', { opacity: 0, y: 18, stagger: 0.08, duration: 0.5, clearProps: 'opacity,transform' }, '-=0.3')
        .from('.sarvam-showcase-card', { opacity: 0, y: 35, scale: 0.98, duration: 0.85, clearProps: 'opacity,transform' }, '-=0.2')

      // Section Headers Reveal on Scroll
      gsap.utils.toArray<HTMLElement>('.sarvam-section-header').forEach((header) => {
        gsap.fromTo(
          header,
          { opacity: 0, y: 35 },
          {
            scrollTrigger: {
              trigger: header,
              start: 'top 88%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            duration: 0.75,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )
      })

      // Live Studio Container Scroll Entrance
      if (studioRef.current) {
        gsap.fromTo(
          '.sarvam-studio-container',
          { opacity: 0, y: 40 },
          {
            scrollTrigger: {
              trigger: studioRef.current,
              start: 'top 80%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            duration: 0.85,
            ease: 'power3.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // Volume Section Metric Cards Stagger & Counter Animation
      if (volumeRef.current) {
        gsap.fromTo(
          '.sarvam-metric-card',
          { opacity: 0, y: 30 },
          {
            scrollTrigger: {
              trigger: volumeRef.current,
              start: 'top 85%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            stagger: 0.08,
            duration: 0.65,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )

        // Animate counter values
        const counterTarget = { minutes: 0, latency: 720, uptime: 95.0, lines: 0 }
        ScrollTrigger.create({
          trigger: volumeRef.current,
          start: 'top 85%',
          once: true,
          onEnter: () => {
            gsap.to(counterTarget, {
              minutes: 4.8,
              latency: 420,
              uptime: 99.99,
              lines: 10000,
              duration: 2.2,
              ease: 'power2.out',
              onUpdate: () => {
                setMetricCounts({
                  minutes: `${counterTarget.minutes.toFixed(1)}M+`,
                  latency: `< ${Math.round(counterTarget.latency)}ms`,
                  uptime: `${counterTarget.uptime.toFixed(2)}%`,
                  lines: `${Math.round(counterTarget.lines).toLocaleString()}+`,
                })
              },
            })
          },
        })
      }

      // Features 6-Card Grid Stagger Entrance
      if (featuresRef.current) {
        gsap.fromTo(
          '.sarvam-feature-card',
          { opacity: 0, y: 35, scale: 0.98 },
          {
            scrollTrigger: {
              trigger: featuresRef.current,
              start: 'top 80%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            scale: 1,
            stagger: 0.07,
            duration: 0.7,
            ease: 'power3.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // Telephony Pipeline Steps Stagger
      if (telephonyRef.current) {
        gsap.fromTo(
          '.sarvam-process-step',
          { opacity: 0, y: 35 },
          {
            scrollTrigger: {
              trigger: telephonyRef.current,
              start: 'top 82%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            stagger: 0.12,
            duration: 0.7,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // Audio Showcase Cards Stagger
      if (audioRef.current) {
        gsap.fromTo(
          '.sarvam-audio-card',
          { opacity: 0, y: 30 },
          {
            scrollTrigger: {
              trigger: audioRef.current,
              start: 'top 85%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            stagger: 0.08,
            duration: 0.7,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // Security Cards Stagger
      if (securityRef.current) {
        gsap.fromTo(
          '.sarvam-sec-card',
          { opacity: 0, y: 30 },
          {
            scrollTrigger: {
              trigger: securityRef.current,
              start: 'top 85%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            stagger: 0.08,
            duration: 0.65,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // FAQ Accordion Stagger
      if (faqRef.current) {
        gsap.fromTo(
          '.sarvam-faq-item',
          { opacity: 0, y: 24 },
          {
            scrollTrigger: {
              trigger: faqRef.current,
              start: 'top 85%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            stagger: 0.06,
            duration: 0.6,
            ease: 'power2.out',
            clearProps: 'opacity,transform',
          }
        )
      }

      // Creative Launch CTA Card Stagger
      if (ctaRef.current) {
        gsap.fromTo(
          '.sarvam-cta-card',
          { opacity: 0, y: 40, scale: 0.97 },
          {
            scrollTrigger: {
              trigger: ctaRef.current,
              start: 'top 85%',
              toggleActions: 'play none none none',
              once: true,
            },
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.85,
            ease: 'power3.out',
            clearProps: 'opacity,transform',
          }
        )
      }
    })

    // Refresh ScrollTrigger to calculate accurate bounds after layout settles
    const refreshTimer = setTimeout(() => {
      ScrollTrigger.refresh()
    }, 150)

    const handleResize = () => {
      ScrollTrigger.refresh()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      clearTimeout(refreshTimer)
      window.removeEventListener('resize', handleResize)
      ctx.revert()
      gsap.ticker.remove(tickerCb)
      window.removeEventListener('scroll', handleWindowScroll)
      lenis.destroy()
    }
  }, [])

  // Smooth Section Navigation
  const scrollToSection = (e: React.MouseEvent<HTMLAnchorElement>, targetId: string) => {
    e.preventDefault()
    setMobileMenuOpen(false)
    setActiveNav(targetId)
    const el = document.getElementById(targetId)
    if (el) {
      if (lenisRef.current) {
        lenisRef.current.scrollTo(el, { offset: -70, duration: 1.15 })
      } else {
        el.scrollIntoView({ behavior: 'smooth' })
      }
    }
  }

  // Feature Card 3D Perspective Tilt on Mouse Move
  const handleCardMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const card = e.currentTarget
    const rect = card.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    const rotateX = ((y - centerY) / centerY) * -6
    const rotateY = ((x - centerX) / centerX) * 6

    card.style.setProperty('--mouse-x', `${x}px`)
    card.style.setProperty('--mouse-y', `${y}px`)
    card.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateY(-4px)`
  }

  // Feature Card 3D Tilt Reset on Mouse Leave
  const handleCardMouseLeave = (e: React.MouseEvent<HTMLDivElement>) => {
    const card = e.currentTarget
    card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0px)'
  }

  const formatSeconds = (s: number) => {
    const mins = Math.floor(s / 60)
    const secs = s % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  return (
    <div className="sarvam-landing-root">
      {/* Dynamic Reading Scroll Progress Bar */}
      <div className="sarvam-scroll-progress" style={{ width: `${scrollProgress}%` }} />
      <div className="sarvam-ambient-mesh" />

      {/* ----------------------------------------------------------------------
          1. FIXED MODERN NAVBAR
          ---------------------------------------------------------------------- */}
      <header className={`sarvam-nav-header ${isScrolled ? 'scrolled' : ''}`}>
        <div className="sarvam-nav-container">
          <Link to="/" className="sarvam-wordmark-link">
            <div className="sarvam-logo-icon">CF</div>
            <div className="sarvam-logo-text-group">
              <span className="sarvam-brand-name">CallForge</span>
              <span className="sarvam-logo-pill">
                <span className="sarvam-logo-pill-dot" />
                <span>AI Voice OS</span>
              </span>
            </div>
          </Link>

          <nav className="sarvam-nav-links">
            <a
              href="#live-demo"
              className={`sarvam-nav-link ${activeNav === 'live-demo' ? 'active' : ''}`}
              onClick={(e) => scrollToSection(e, 'live-demo')}
            >
              <span>Live Sandbox</span>
            </a>
            <a
              href="#features"
              className={`sarvam-nav-link ${activeNav === 'features' ? 'active' : ''}`}
              onClick={(e) => scrollToSection(e, 'features')}
            >
              <span>Capabilities</span>
            </a>
            <a
              href="#telephony"
              className={`sarvam-nav-link ${activeNav === 'telephony' ? 'active' : ''}`}
              onClick={(e) => scrollToSection(e, 'telephony')}
            >
              <span>SIP Telephony</span>
            </a>
            <a
              href="#audio-showcase"
              className={`sarvam-nav-link ${activeNav === 'audio-showcase' ? 'active' : ''}`}
              onClick={(e) => scrollToSection(e, 'audio-showcase')}
            >
              <span>Voices</span>
            </a>
            <a
              href="#faq"
              className={`sarvam-nav-link ${activeNav === 'faq' ? 'active' : ''}`}
              onClick={(e) => scrollToSection(e, 'faq')}
            >
              <span>FAQ</span>
            </a>
          </nav>

          <div className="sarvam-nav-actions">
            {user ? (
              <Link to="/overview" className="sarvam-btn-pill">
                <Radio size={14} />
                <span>Console Dashboard</span>
              </Link>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode('login')
                    setAuthModalOpen(true)
                  }}
                  className="sarvam-btn-signin"
                >
                  Sign in
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode('signup')
                    setAuthModalOpen(true)
                  }}
                  className="sarvam-btn-pill sarvam-btn-nav-cta"
                >
                  <span>Start building free</span>
                  <ArrowRight size={13} />
                </button>
              </>
            )}

            <button
              type="button"
              className="sarvam-mobile-toggle"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
            >
              {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>

        {/* Mobile menu dropdown */}
        <div className={`sarvam-mobile-drawer ${mobileMenuOpen ? 'open' : ''}`}>
          <div className="sarvam-mobile-nav-list">
            <a
              href="#live-demo"
              onClick={(e) => scrollToSection(e, 'live-demo')}
              className="sarvam-mobile-nav-item"
            >
              <Headphones size={16} style={{ color: '#6366f1' }} />
              <span>Live Sandbox</span>
            </a>
            <a
              href="#features"
              onClick={(e) => scrollToSection(e, 'features')}
              className="sarvam-mobile-nav-item"
            >
              <Sparkles size={16} style={{ color: '#10b981' }} />
              <span>Capabilities</span>
            </a>
            <a
              href="#telephony"
              onClick={(e) => scrollToSection(e, 'telephony')}
              className="sarvam-mobile-nav-item"
            >
              <Radio size={16} style={{ color: '#f59e0b' }} />
              <span>SIP Telephony</span>
            </a>
            <a
              href="#audio-showcase"
              onClick={(e) => scrollToSection(e, 'audio-showcase')}
              className="sarvam-mobile-nav-item"
            >
              <Bot size={16} style={{ color: '#06b6d4' }} />
              <span>Voice Showcase</span>
            </a>
            <a
              href="#faq"
              onClick={(e) => scrollToSection(e, 'faq')}
              className="sarvam-mobile-nav-item"
            >
              <MessageSquare size={16} style={{ color: '#8b5cf6' }} />
              <span>FAQ</span>
            </a>
          </div>

          <div style={{ paddingTop: '0.75rem', borderTop: '1px solid #e5e7eb' }}>
            {user ? (
              <Link to="/overview" className="sarvam-btn-pill" style={{ width: '100%', justifyContent: 'center' }}>
                <Radio size={14} />
                <span>Console Dashboard</span>
              </Link>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode('login')
                    setAuthModalOpen(true)
                    setMobileMenuOpen(false)
                  }}
                  className="sarvam-btn-secondary"
                  style={{ width: '100%', justifyContent: 'center' }}
                >
                  Sign in
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode('signup')
                    setAuthModalOpen(true)
                    setMobileMenuOpen(false)
                  }}
                  className="sarvam-btn-pill"
                  style={{ width: '100%', justifyContent: 'center' }}
                >
                  <span>Start building free</span>
                  <ArrowRight size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* ----------------------------------------------------------------------
          2. HERO SECTION
          ---------------------------------------------------------------------- */}
      <section className="sarvam-hero" ref={heroRef}>
        <div className="sarvam-hero-aura-glow" />

        {/* Floating Telemetry Badges */}
        <div className="sarvam-floating-badge badge-left">
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
          <span>382ms Telephony Turnaround</span>
        </div>
        <div className="sarvam-floating-badge badge-right">
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#6366f1', boxShadow: '0 0 8px #6366f1' }} />
          <span>Native Asterisk 9092 AudioSocket</span>
        </div>

        <div className="sarvam-micro-tag">
          <span className="sarvam-hero-pulse-dot" />
          <span>CALLFORGE VOICE AGENTS • VAD &lt; 20MS</span>
        </div>

        <h1 className="sarvam-hero-title">
          Voice agents that <span className="highlight-text">sound human</span> and deliver results.
        </h1>

        <p className="sarvam-hero-subtitle">
          One platform to build, launch, and scale voice agents that carry customer context into every call and work each conversation toward your business outcomes.
        </p>

        <div className="sarvam-hero-ctas">
          {user ? (
            <Link to="/overview" className="sarvam-btn-pill sarvam-btn-pill-lg">
              <span>Open Developer Console</span>
              <ArrowRight size={18} />
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => {
                setAuthMode('signup')
                setAuthModalOpen(true)
              }}
              className="sarvam-btn-pill sarvam-btn-pill-lg"
            >
              <span>Start building free</span>
              <ArrowRight size={18} />
            </button>
          )}

          <a
            href="#live-demo"
            onClick={(e) => scrollToSection(e, 'live-demo')}
            className="sarvam-btn-secondary sarvam-btn-pill-lg"
          >
            <Headphones size={18} />
            <span>Try Live Simulator</span>
          </a>
        </div>

        <p className="sarvam-hero-microcopy">
          Free credits on signup • No credit card needed • Native Asterisk AudioSocket &amp; SIP ready
        </p>

        {/* ------------------------------------------------------------------
            3. LAUNCH STEPPER PILLS (Describe -> Test -> Get a number -> Go live)
            ------------------------------------------------------------------ */}
        <div className="sarvam-stepper-container" ref={stepperRef}>
          <div className="sarvam-stepper-line" />
          {steps.map((step, idx) => {
            const Icon = step.icon
            const isActive = activeStep === idx
            return (
              <div
                key={step.title}
                className={`sarvam-stepper-pill ${isActive ? 'active' : ''}`}
                onClick={() => setActiveStep(idx)}
              >
                <div className="sarvam-step-icon-wrap">
                  <Icon size={14} />
                </div>
                <span>{step.title}</span>
              </div>
            )
          })}
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          4. HERO VISUALIZATION / ACTIVE STEP CARD
          ---------------------------------------------------------------------- */}
      <div className="sarvam-showcase-wrapper" ref={showcaseRef}>
        <div className="sarvam-showcase-card">
          <div className="sarvam-showcase-topbar">
            <div className="sarvam-traffic-dots">
              <div className="sarvam-traffic-dot red" />
              <div className="sarvam-traffic-dot yellow" />
              <div className="sarvam-traffic-dot green" />
              <span style={{ fontSize: '0.8rem', color: '#64748b', marginLeft: '0.5rem', fontFamily: 'var(--font-mono)' }}>
                callforge://runtime/cluster-01/telephony-bridge
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem', color: '#10b981', fontWeight: 600 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#10b981' }} />
              <span>PJSIP RUNTIME ONLINE</span>
            </div>
          </div>

          <div style={{ padding: '2.5rem 2rem', background: '#fafafa' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '2rem', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'inline-flex', padding: '0.25rem 0.65rem', background: '#e0e7ff', color: '#4338ca', borderRadius: '6px', fontSize: '0.75rem', fontWeight: 700, marginBottom: '0.75rem' }}>
                  STEP {activeStep + 1} OF 4: {steps[activeStep].title.toUpperCase()}
                </div>
                <h3 style={{ fontSize: '1.65rem', fontWeight: 700, color: '#111827', margin: '0 0 0.85rem', letterSpacing: '-0.02em' }}>
                  {steps[activeStep].desc}
                </h3>
                <p style={{ color: '#4b5563', fontSize: '0.95rem', lineHeight: 1.6, margin: '0 0 1.5rem' }}>
                  {activeStep === 0 &&
                    'Craft your agent instructions in plain English, Hinglish, or Hindi. Connect real-time REST endpoints, CRM memory stores, and database schemas with zero custom boilerplate.'}
                  {activeStep === 1 &&
                    'Stream two-way audio through the browser sandbox at sub-420ms turnaround. Validate barge-in interruptions, latency breakdown waterfalls, and intent routing before dialing real phones.'}
                  {activeStep === 2 &&
                    'Attach instant SIP trunks or route directly to your existing Asterisk, FreePBX, Cisco, or Twilio numbers. Provision local DIDs in over 50 countries with 1-click dialplan mapping.'}
                  {activeStep === 3 &&
                    'Handle thousands of simultaneous outbound campaigns or inbound customer queues. All calls stream via bare-metal AudioSocket TCP with zero cloud relay jitter.'}
                </p>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <button
                    type="button"
                    onClick={() => {
                      const next = (activeStep + 1) % steps.length
                      setActiveStep(next)
                    }}
                    className="sarvam-btn-pill"
                  >
                    <span>Next step: {steps[(activeStep + 1) % steps.length].title}</span>
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>

              {/* Code / Visual Box */}
              <div
                style={{
                  background: '#0f172a',
                  borderRadius: '16px',
                  padding: '1.5rem',
                  border: '1px solid #1e293b',
                  color: '#f8fafc',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.85rem',
                  boxShadow: '0 12px 30px rgba(0, 0, 0, 0.25)',
                }}
              >
                <div style={{ color: '#64748b', fontSize: '0.72rem', marginBottom: '0.75rem', borderBottom: '1px solid #1e293b', paddingBottom: '0.5rem' }}>
                  // Asterisk dialplan &amp; AudioSocket configuration
                </div>
                <div style={{ color: '#38bdf8' }}>[callforge-voice-inbound]</div>
                <div style={{ color: '#94a3b8' }}>exten =&gt; 1001,1,NoOp(AudioSocket CallForge AI)</div>
                <div style={{ color: '#94a3b8' }}>same  =&gt; n,Answer()</div>
                <div style={{ color: '#a7f3d0' }}>{"same  => n,AudioSocket(127.0.0.1:9092,${UNIQUEID})"}</div>
                <div style={{ color: '#94a3b8' }}>same  =&gt; n,Hangup()</div>
                <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', color: '#10b981', fontSize: '0.75rem' }}>
                  <span>✓ 8kHz Linear PCM</span>
                  <span>✓ Latency: 382ms</span>
                  <span>✓ Silero VAD</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ----------------------------------------------------------------------
          5. INTERACTIVE 3-COLUMN STUDIO: "EXPERIENCE A VOICE AGENT, LIVE"
          ---------------------------------------------------------------------- */}
      <section id="live-demo" ref={studioRef} className="sarvam-live-section">
        <div className="sarvam-section-header">
          <h2 className="sarvam-section-title">
            Experience a voice<br />agent, live.
          </h2>
          <p className="sarvam-section-desc">
            Sales, collections, support, bookings. Pick one and have the conversation yourself.
          </p>
        </div>

        <div className="sarvam-studio-container">
          {/* Column 1: Choose an agent */}
          <div className="sarvam-col-agents">
            <div className="sarvam-col-title">
              <span>Choose an agent</span>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>{AGENT_SCENARIOS.length} Scenarios</span>
            </div>

            <div className="sarvam-agent-list">
              {AGENT_SCENARIOS.map((agent) => {
                const Icon = agent.icon
                const isSelected = selectedAgent.id === agent.id
                return (
                  <div
                    key={agent.id}
                    className={`sarvam-agent-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => setSelectedAgent(agent)}
                  >
                    <div className={`sarvam-agent-icon ${agent.iconColor}`}>
                      <Icon size={17} />
                    </div>
                    <div className="sarvam-agent-meta">
                      <div className="sarvam-agent-name">{agent.name}</div>
                      <div className="sarvam-agent-tag">{agent.category}</div>
                    </div>
                  </div>
                )
              })}
            </div>

            <div style={{ marginTop: 'auto', paddingTop: '1.25rem', borderTop: '1px solid #e5e7eb' }}>
              <button
                type="button"
                onClick={() => {
                  setAuthMode('signup')
                  setAuthModalOpen(true)
                }}
                className="sarvam-btn-secondary"
                style={{ width: '100%', fontSize: '0.82rem' }}
              >
                <Bot size={14} />
                <span>Build Custom Agent</span>
              </button>
            </div>
          </div>

          {/* Column 2: Agent Configuration & Prompt Context */}
          <div className="sarvam-col-config">
            <div className="sarvam-config-block">
              <div className="sarvam-config-label">
                <span>System Instructions &amp; Goal</span>
                <span style={{ color: '#10b981' }}>Active</span>
              </div>
              <div className="sarvam-prompt-box">
                {selectedAgent.systemPrompt}
              </div>
            </div>

            <div className="sarvam-config-block">
              <div className="sarvam-config-label">
                <span>Language &amp; Code-Switching</span>
                <span style={{ color: '#6366f1' }}>{activeLanguage}</span>
              </div>
              <div className="sarvam-lang-pills">
                {['English', 'Hindi (हिंदी)', 'Hinglish', 'Tamil (தமிழ்)', 'Telugu (తెలుగు)', 'Marathi (मराठी)'].map((lang) => (
                  <button
                    key={lang}
                    type="button"
                    className={`sarvam-lang-pill ${activeLanguage === lang ? 'active' : ''}`}
                    onClick={() => {
                      setActiveLanguage(lang)
                      show(`Voice language set to ${lang}`)
                    }}
                  >
                    {lang}
                  </button>
                ))}
              </div>
            </div>

            <div className="sarvam-config-block">
              <div className="sarvam-config-label">
                <span>Connected External Tools</span>
                <span style={{ color: '#64748b' }}>3 active</span>
              </div>
              <div className="sarvam-tool-list">
                {selectedAgent.tools.map((tool) => (
                  <div key={tool} className="sarvam-tool-badge">
                    <Database size={12} style={{ color: '#6366f1' }} />
                    <span>{tool}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="sarvam-config-block">
              <div className="sarvam-config-label">
                <span>Telephony Pipeline Specs</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.5rem', fontSize: '0.78rem', color: '#475569' }}>
                <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>VAD INTERRUPT</div>
                  <div style={{ fontWeight: 600, color: '#111827' }}>&lt; 20ms Silero</div>
                </div>
                <div style={{ background: '#f8fafc', padding: '0.5rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                  <div style={{ fontSize: '0.68rem', color: '#94a3b8' }}>AUDIO CODEC</div>
                  <div style={{ fontWeight: 600, color: '#111827' }}>SLIN16 8000Hz</div>
                </div>
              </div>
            </div>
          </div>

          {/* Column 3: Live Real-Time Simulator & Softphone */}
          <div className="sarvam-col-simulator">
            <div className={`sarvam-phone-card ${isCallActive ? 'active-call' : ''} ${isBargedIn ? 'barged' : ''}`}>
              <div className="sarvam-phone-header">
                <div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#111827' }}>
                    {selectedAgent.name}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: '#64748b' }}>
                    Asterisk PJSIP Extension #1001
                  </div>
                </div>

                <div className="sarvam-call-status-badge">
                  <span className="sarvam-status-pulse" />
                  <span>{isCallActive ? `Live (${formatSeconds(callDuration)})` : 'Standby'}</span>
                </div>
              </div>

              {/* Real-Time Waveform Canvas */}
              <div className="sarvam-wave-container">
                <canvas ref={canvasRef} width={340} height={80} className="sarvam-wave-canvas" />
                <div
                  style={{
                    position: 'absolute',
                    bottom: '6px',
                    left: '10px',
                    fontSize: '0.65rem',
                    color: isAgentSpeaking ? '#34d399' : '#94a3b8',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                  }}
                >
                  {isAgentSpeaking ? 'AGENT TRANSMITTING AUDIO (TTS 8kHz)' : isCallActive ? 'LISTENING (VAD ACTIVE)' : 'READY TO CONNECT'}
                </div>
              </div>

              {/* Barge-In Alert Banner */}
              {isBargedIn && (
                <div style={{ background: '#fef3c7', border: '1px solid #f59e0b', color: '#b45309', padding: '0.4rem 0.75rem', borderRadius: '8px', fontSize: '0.75rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <Zap size={14} />
                  <span>Silero VAD Barge-In Detected: Speech interrupted in 18ms</span>
                </div>
              )}

              {/* Transcript Chat Stream */}
              <div className="sarvam-transcript-stream">
                {chatTranscript.map((item, i) => {
                  const isCurrentTurn = isCallActive && activeCallTurn === i
                  return (
                    <div
                      key={i}
                      className={`sarvam-bubble ${item.speaker} ${isCurrentTurn ? 'active-turn' : ''}`}
                      onClick={() => {
                        if (isCallActive) {
                          if (callTurnTimerRef.current) clearTimeout(callTurnTimerRef.current)
                          speakLiveTurn(i)
                        }
                      }}
                      style={{ cursor: isCallActive ? 'pointer' : 'default' }}
                      title={isCallActive ? 'Click to replay or speak this turn' : undefined}
                    >
                      <div>{item.text}</div>
                      <div className="sarvam-bubble-meta">
                        <span>
                          {item.speaker === 'agent' ? `${selectedAgent.name} (AI)` : 'Caller'}
                          {isCurrentTurn && ' • Speaking now'}
                        </span>
                        {item.speaker === 'agent' && (
                          <span className="sarvam-latency-tag">
                            STT: {item.sttMs}ms • LLM: {item.llmMs}ms • TTS: {item.ttsMs}ms
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Call Controls */}
              <div className="sarvam-controls-row">
                <button
                  type="button"
                  onClick={handleToggleCall}
                  className={`sarvam-btn-call ${isCallActive ? 'in-call' : ''}`}
                >
                  {isCallActive ? (
                    <>
                      <PhoneOff size={16} />
                      <span>End Live Call</span>
                    </>
                  ) : (
                    <>
                      <PhoneCall size={16} />
                      <span>Start Live Call</span>
                    </>
                  )}
                </button>

                <button
                  type="button"
                  onClick={handleBargeIn}
                  className="sarvam-btn-barge"
                  title="Test immediate caller interruption"
                >
                  <Zap size={14} style={{ color: '#f59e0b' }} />
                  <span>Interrupt (Barge-in)</span>
                </button>

                {isCallActive && (
                  <button
                    type="button"
                    onClick={handleNextTurn}
                    className="sarvam-btn-barge"
                    title="Skip to next conversation turn"
                    style={{ background: '#f1f5f9', border: '1px solid #cbd5e1', color: '#1e293b' }}
                  >
                    <span>Next ⏭️</span>
                  </button>
                )}
              </div>

              {/* Real-time Telemetry Bar */}
              <div className="sarvam-telemetry-bar">
                <div className="sarvam-telemetry-item">
                  <div className="sarvam-telemetry-label">Roundtrip</div>
                  <div className="sarvam-telemetry-value" style={{ color: '#10b981' }}>{telemetryLatency}ms</div>
                </div>
                <div className="sarvam-telemetry-item">
                  <div className="sarvam-telemetry-label">Packet Loss</div>
                  <div className="sarvam-telemetry-value">0.00%</div>
                </div>
                <div className="sarvam-telemetry-item">
                  <div className="sarvam-telemetry-label">SIP Jitter</div>
                  <div className="sarvam-telemetry-value">{telemetryJitter}ms</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          6. TRUSTED BY TEAMS RUNNING SERIOUS CALL VOLUMES
          ---------------------------------------------------------------------- */}
      <section className="sarvam-volume-section" ref={volumeRef}>
        <div style={{ maxWidth: '800px', margin: '0 auto', padding: '0 1.5rem' }}>
          <h2 style={{ fontSize: 'clamp(1.8rem, 3.2vw, 2.4rem)', fontWeight: 700, color: '#111827', margin: '0 0 0.75rem', letterSpacing: '-0.02em' }}>
            Trusted by teams running serious call volumes.
          </h2>
          <p style={{ color: '#64748b', fontSize: '1.02rem', lineHeight: 1.6 }}>
            Engineered from the ground up for high-concurrency telephony, zero-packet-drop audio bridges, and sovereign compliance.
          </p>
        </div>

        <div className="sarvam-metrics-grid">
          <div className="sarvam-metric-card">
            <div className="sarvam-metric-num">{metricCounts.minutes}</div>
            <div className="sarvam-metric-label">Monthly telephony minutes</div>
          </div>
          <div className="sarvam-metric-card">
            <div className="sarvam-metric-num" style={{ color: '#10b981' }}>{metricCounts.latency}</div>
            <div className="sarvam-metric-label">Average turnaround latency</div>
          </div>
          <div className="sarvam-metric-card">
            <div className="sarvam-metric-num">{metricCounts.uptime}</div>
            <div className="sarvam-metric-label">Carrier uptime SLA</div>
          </div>
          <div className="sarvam-metric-card">
            <div className="sarvam-metric-num" style={{ color: '#6366f1' }}>{metricCounts.lines}</div>
            <div className="sarvam-metric-label">Concurrent lines per cluster</div>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          7. BUILD. TEST. GO LIVE. (6-CARD FEATURE GRID)
          ---------------------------------------------------------------------- */}
      <section id="features" ref={featuresRef} className="sarvam-features-section">
        <div className="sarvam-section-header">
          <h2 className="sarvam-section-title">
            Build. Test. Go live.
          </h2>
          <p className="sarvam-section-desc">
            Everything you need to ship conversational voice agents that understand nuances, execute actions, and resolve calls end-to-end.
          </p>
        </div>

        <div className="sarvam-features-grid">
          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Sparkles size={22} />
            </div>
            <h3 className="sarvam-feature-title">From idea to live calls in minutes.</h3>
            <p className="sarvam-feature-desc">
              Write instructions in plain English or regional languages. Configure tool schema and knowledge files with an intuitive developer interface.
            </p>
          </div>

          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Database size={22} />
            </div>
            <h3 className="sarvam-feature-title">Memory that carries across calls.</h3>
            <p className="sarvam-feature-desc">
              When a customer calls back next week, the agent recognizes their history, open tickets, and past preferences with zero repetitive questioning.
            </p>
          </div>

          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Zap size={22} />
            </div>
            <h3 className="sarvam-feature-title">Made for unscripted conversations.</h3>
            <p className="sarvam-feature-desc">
              Handles natural speech hesitations, ambient background noise, and sudden topic pivots effortlessly with instant Silero barge-in detection.
            </p>
          </div>

          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Layers size={22} />
            </div>
            <h3 className="sarvam-feature-title">Agents with all the right context.</h3>
            <p className="sarvam-feature-desc">
              Connect PostgreSQL, Snowflake, Salesforce, or custom REST APIs to execute live order lookups and payment dispatches mid-conversation.
            </p>
          </div>

          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Activity size={22} />
            </div>
            <h3 className="sarvam-feature-title">Analyze every call automatically.</h3>
            <p className="sarvam-feature-desc">
              Comprehensive sentiment tracking, latency waterfall breakdowns, structured JSON summaries, and automated quality assurance on 100% of calls.
            </p>
          </div>

          <div className="sarvam-feature-card" onMouseMove={handleCardMouseMove} onMouseLeave={handleCardMouseLeave}>
            <div className="sarvam-feature-icon">
              <Server size={22} />
            </div>
            <h3 className="sarvam-feature-title">Scale without breaking.</h3>
            <p className="sarvam-feature-desc">
              High-throughput Asterisk PBX AudioSocket streaming runs on your sovereign infrastructure or private cloud with zero third-party relay overhead.
            </p>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          8. PROCESS PIPELINE: LIVE IN DAYS, NOT MONTHS
          ---------------------------------------------------------------------- */}
      <section id="telephony" ref={telephonyRef} className="sarvam-process-section">
        <div className="sarvam-section-header">
          <h2 className="sarvam-section-title">
            Live in days, not months.
          </h2>
          <p className="sarvam-section-desc">
            Skip complex legacy telephony integrations. Deploy straight into your carrier SIP trunks or run with our managed numbers.
          </p>
        </div>

        <div className="sarvam-process-steps">
          <div className="sarvam-process-step">
            <div className="sarvam-step-number">STEP 01</div>
            <h3 className="sarvam-step-title">Build</h3>
            <p className="sarvam-step-body">
              Define the agent persona, upload your knowledge documents, and attach API tools. Our sovereign reasoning engine generates low-latency execution graphs.
            </p>
          </div>

          <div className="sarvam-process-step">
            <div className="sarvam-step-number">STEP 02</div>
            <h3 className="sarvam-step-title">Test</h3>
            <p className="sarvam-step-body">
              Run real audio through our interactive browser softphone. Dial into private extensions and inspect sub-second STT, LLM, and TTS latency waterfalls.
            </p>
          </div>

          <div className="sarvam-process-step">
            <div className="sarvam-step-number">STEP 03</div>
            <h3 className="sarvam-step-title">Go live</h3>
            <p className="sarvam-step-body">
              Map your Asterisk dialplan or point your carrier SIP trunks directly to CallForge. Scale from 10 to 10,000 concurrent lines with zero degradation.
            </p>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          9. AUDIO SHOWCASE: HEAR OUR VOICE AGENTS AT WORK
          ---------------------------------------------------------------------- */}
      <section id="audio-showcase" ref={audioRef} className="sarvam-audio-section">
        <div className="sarvam-section-header">
          <h2 className="sarvam-section-title">
            Hear our voice agents at work.
          </h2>
          <p className="sarvam-section-desc">
            Natural cadence, lifelike intonation, and native Indian language accents. Listen to sample conversations recorded directly from telephony lines.
          </p>
        </div>

        <div className="sarvam-audio-grid">
          {AUDIO_SHOWCASES.map((sample) => {
            const isPlaying = playingAudioId === sample.id
            return (
              <div key={sample.id} className={`sarvam-audio-card ${isPlaying ? 'playing' : ''}`}>
                <div className="sarvam-audio-header">
                  <div className="sarvam-audio-agent-info">
                    <div className="sarvam-audio-avatar">
                      {isPlaying ? <Radio size={20} className="sarvam-status-pulse" /> : <Headphones size={20} />}
                    </div>
                    <div>
                      <div className="sarvam-audio-agent-name">
                        <span>{sample.agent}</span>
                      </div>
                      <div className="sarvam-audio-role">
                        {sample.role} • {sample.scenario}
                      </div>
                    </div>
                  </div>

                  <span
                    className="sarvam-lang-badge"
                    style={{
                      background: sample.badgeBg,
                      color: sample.badgeColor,
                      border: `1px solid ${sample.badgeColor}33`,
                    }}
                  >
                    {sample.language}
                  </span>
                </div>

                <div className="sarvam-audio-player-bar">
                  <div className="sarvam-player-controls-row">
                    <button
                      type="button"
                      onClick={() => handleToggleAudio(sample.id)}
                      className="sarvam-play-btn"
                      aria-label={isPlaying ? 'Pause sample' : 'Play sample'}
                    >
                      {isPlaying ? <Pause size={18} /> : <Play size={18} style={{ marginLeft: 2 }} />}
                    </button>

                    <div className="sarvam-wave-bars">
                      {waveHeights.map((h, idx) => (
                        <div
                          key={idx}
                          className={`sarvam-wave-bar ${isPlaying ? 'active' : ''}`}
                          style={{
                            height: isPlaying ? `${Math.min(30, Math.max(6, h))}px` : `${Math.max(6, (idx % 4 + 2) * 3.5)}px`,
                            animationDelay: `${idx * 0.05}s`,
                          }}
                        />
                      ))}
                    </div>

                    <div className="sarvam-audio-time-meta">
                      <span>{isPlaying ? `${formatSeconds(Math.floor((playbackProgress / 100) * (parseInt(sample.duration.split(':')[1], 10) || 28)))}` : '00:00'}</span>
                      <span>/</span>
                      <span>{sample.duration}</span>
                    </div>
                  </div>

                  {/* Audio progress bar */}
                  <div className="sarvam-audio-progress-track">
                    <div
                      className="sarvam-audio-progress-fill"
                      style={{ width: isPlaying ? `${playbackProgress}%` : '0%' }}
                    />
                  </div>
                </div>

                <div className="sarvam-audio-transcript-box">
                  <span style={{ fontSize: '0.74rem', color: '#64748b', fontWeight: 600, display: 'block', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    Verbatim Telephony Audio Transcript
                  </span>
                  "{sample.transcript}"
                </div>

                <div className="sarvam-audio-footer">
                  <div className="sarvam-audio-live-pill">
                    <span className="sarvam-audio-live-dot" />
                    <span>{isPlaying ? 'Synthesizing Live SLIN16 Audio' : 'Recorded 8kHz Linear PCM'}</span>
                  </div>
                  <div>Carrier Turnaround: {sample.latency}</div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          10. ENTERPRISE & PRIVACY SECTION
          ---------------------------------------------------------------------- */}
      <section className="sarvam-security-section" ref={securityRef}>
        <div style={{ maxWidth: '800px', margin: '0 auto', textAlign: 'center', padding: '0 1.5rem' }}>
          <h2 style={{ fontSize: 'clamp(2rem, 3.8vw, 2.6rem)', fontWeight: 700, letterSpacing: '-0.02em', margin: '0 0 1rem' }}>
            Enterprise-ready. Built for privacy.
          </h2>
          <p style={{ color: '#94a3b8', fontSize: '1.05rem', lineHeight: 1.6 }}>
            Designed for regulated industries where customer voice data and compliance cannot be compromised.
          </p>
        </div>

        <div className="sarvam-sec-grid">
          <div className="sarvam-sec-card">
            <div style={{ width: 36, height: 36, borderRadius: '8px', background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#38bdf8', marginBottom: '1rem' }}>
              <Shield size={20} />
            </div>
            <h3 className="sarvam-sec-title">Enterprise-grade security</h3>
            <p className="sarvam-sec-desc">
              End-to-end TLS/SRTP voice encryption, role-based access control (RBAC), and strict SOC-2 Type II audit trail readiness.
            </p>
          </div>

          <div className="sarvam-sec-card">
            <div style={{ width: 36, height: 36, borderRadius: '8px', background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#10b981', marginBottom: '1rem' }}>
              <Lock size={20} />
            </div>
            <h3 className="sarvam-sec-title">Built for privacy</h3>
            <p className="sarvam-sec-desc">
              Zero data retention guarantees. Your audio streams and customer transcripts are never used to train public foundational models.
            </p>
          </div>

          <div className="sarvam-sec-card">
            <div style={{ width: 36, height: 36, borderRadius: '8px', background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#a855f7', marginBottom: '1rem' }}>
              <Server size={20} />
            </div>
            <h3 className="sarvam-sec-title">On-Prem &amp; Private VPC</h3>
            <p className="sarvam-sec-desc">
              Deploy our complete Asterisk AudioSocket telephony daemon and sovereign model inference within your own VPC or physical datacenter.
            </p>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          11. FAQ ACCORDION
          ---------------------------------------------------------------------- */}
      <section id="faq" ref={faqRef} className="sarvam-faq-section">
        <div className="sarvam-section-header">
          <h2 className="sarvam-section-title">
            Frequently asked questions.
          </h2>
          <p className="sarvam-section-desc">
            Everything you need to know about CallForge voice agents, telephony architecture, and pricing.
          </p>
        </div>

        <div className="sarvam-faq-container">
          {FAQS.map((faq, idx) => {
            const isOpen = openFaqIndex === idx
            return (
              <div key={idx} className={`sarvam-faq-item ${isOpen ? 'open' : ''}`}>
                <button
                  type="button"
                  className="sarvam-faq-trigger"
                  onClick={() => setOpenFaqIndex(isOpen ? null : idx)}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.85rem' }}>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        color: isOpen ? '#4f46e5' : '#94a3b8',
                        background: isOpen ? '#eef2ff' : '#f1f5f9',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '6px',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {`0${idx + 1}`}
                    </span>
                    <span>{faq.question}</span>
                  </span>
                  <ChevronDown
                    size={18}
                    style={{
                      transform: isOpen ? 'rotate(180deg)' : 'rotate(0)',
                      transition: 'transform 0.25s ease',
                      flexShrink: 0,
                      color: isOpen ? '#4f46e5' : '#64748b',
                    }}
                  />
                </button>
                {isOpen && (
                  <div className="sarvam-faq-content">
                    {faq.answer}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          12. CREATIVE AESTHETIC LAUNCH CTA (Replaced Enterprise Deployment Form)
          ---------------------------------------------------------------------- */}
      <section className="sarvam-cta-section" ref={ctaRef}>
        <div className="sarvam-cta-container">
          <div className="sarvam-cta-card">
            {/* Ambient Aurora Glow and Concentric Wave Rings */}
            <div className="sarvam-cta-ambient" />
            <div className="sarvam-cta-rings">
              <div className="sarvam-cta-ring ring-1" />
              <div className="sarvam-cta-ring ring-2" />
              <div className="sarvam-cta-ring ring-3" />
            </div>

            <div className="sarvam-cta-content">
              <div className="sarvam-cta-badge">
                <span className="sarvam-cta-dot" />
                <span>SOVEREIGN VOICE PLATFORM • INSTANT DISPATCH</span>
              </div>

              <h2 className="sarvam-cta-title">
                Ready to voice-enable your stack with human nuance?
              </h2>

              <p className="sarvam-cta-desc">
                Deploy your first high-throughput Asterisk AudioSocket agent in under 2 minutes.
                Zero cloud latency relay. 1,000 free telephony minutes included with every account.
              </p>

              <div className="sarvam-cta-buttons">
                {user ? (
                  <Link to="/overview" className="sarvam-btn-pill sarvam-btn-pill-lg sarvam-cta-primary-btn">
                    <Radio size={18} />
                    <span>Launch Console Fleet</span>
                    <ArrowRight size={18} />
                  </Link>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      setAuthMode('signup')
                      setAuthModalOpen(true)
                    }}
                    className="sarvam-btn-pill sarvam-btn-pill-lg sarvam-cta-primary-btn"
                  >
                    <Sparkles size={18} />
                    <span>Start Building Free</span>
                    <ArrowRight size={18} />
                  </button>
                )}

                <a
                  href="#live-demo"
                  onClick={(e) => scrollToSection(e, 'live-demo')}
                  className="sarvam-btn-secondary sarvam-btn-pill-lg sarvam-cta-secondary-btn"
                >
                  <Headphones size={18} />
                  <span>Test in Sandbox</span>
                </a>
              </div>

              {/* Trust Badges & Telemetry Bar */}
              <div className="sarvam-cta-telemetry">
                <div className="sarvam-cta-stat">
                  <CheckCircle2 size={16} style={{ color: '#10b981' }} />
                  <span>1,000 Free Call Minutes</span>
                </div>
                <div className="sarvam-cta-stat">
                  <CheckCircle2 size={16} style={{ color: '#10b981' }} />
                  <span>Asterisk 20.8+ AudioSocket</span>
                </div>
                <div className="sarvam-cta-stat">
                  <CheckCircle2 size={16} style={{ color: '#10b981' }} />
                  <span>No Credit Card Required</span>
                </div>
                <div className="sarvam-cta-stat">
                  <CheckCircle2 size={16} style={{ color: '#10b981' }} />
                  <span>&lt; 420ms Latency SLA</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ----------------------------------------------------------------------
          13. MINIMALIST FOOTER
          ---------------------------------------------------------------------- */}
      <footer className="sarvam-footer">
        <div className="sarvam-footer-inner">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div className="sarvam-logo-icon">CF</div>
            <span style={{ fontWeight: 700, fontSize: '1.05rem', color: '#111827' }}>CallForge AI</span>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>• Sovereign Telephony Runtime</span>
          </div>

          <div className="sarvam-footer-status">
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />
            <span>All Telephony Nodes Operational (99.99% SLA)</span>
          </div>

          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            © {new Date().getFullYear()} CallForge AI. All rights reserved.
          </div>
        </div>
      </footer>

      {/* Auth Modal */}
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        initialMode={authMode}
        onSuccess={() => navigate('/overview')}
      />
    </div>
  )
}
