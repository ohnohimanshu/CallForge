import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type AvailablePhoneNumber, type DocumentMeta, type Options, type PhonePricing } from '../api'
import { SimulatorModal } from '../components/SimulatorModal'
import { useToast } from '../toast'

export interface SlotDef {
  name: string
  label: string
  required: boolean
  prompt_question: string
}

const DEFAULT_SYSTEM_PROMPT =
  'You are a professional phone agent for a business call. Speak clearly, calmly, and courteously — like a trained receptionist. Use short complete sentences (1–2 per turn). Never use markdown, lists, emojis, stage directions, or filler like "um" or "as an AI". Confirm what the caller needs, answer directly, and offer one helpful next step. If you do not know something, say so briefly and ask a clarifying question. Keep language plain and easy to understand over a phone.'

const DEFAULT_GREETING = 'Thank you for calling. How may I help you today?'

const DEFAULT_SLOTS_PRESET: SlotDef[] = [
  { name: 'caller_name', label: 'Caller Name', required: true, prompt_question: 'May I please have your full name?' },
  { name: 'phone_number', label: 'Phone Number', required: true, prompt_question: 'What is the best phone number to contact you at?' },
  { name: 'caller_intent', label: 'Inquiry Intent', required: true, prompt_question: 'How can our team best assist you today?' },
  { name: 'preferred_time', label: 'Preferred Callback Time', required: false, prompt_question: 'What is your preferred callback time?' },
]

const PROMPT_VARIABLES = [
  { label: '+ Caller ID', value: '{{caller_id}}' },
  { label: '+ Current Time', value: '{{current_time}}' },
  { label: '+ Agent Name', value: '{{agent_name}}' },
  { label: '+ Company Name', value: '{{company_name}}' },
  { label: '+ Caller Language', value: '{{caller_language}}' },
]

type TabKey = 'setup' | 'knowledge' | 'advanced'

const TABS: { id: TabKey; label: string; icon: string }[] = [
  { id: 'setup', label: 'Agent Setup', icon: '⚡' },
  { id: 'knowledge', label: 'Knowledge Base (RAG)', icon: '📚' },
  { id: 'advanced', label: 'Advanced Settings', icon: '🛠️' },
]

const emptyForm = {
  name: '',
  description: '',
  extension: '2000',
  language: 'auto',
  llm_model: 'llama3.2:3b-instruct-q4_K_M',
  system_prompt: DEFAULT_SYSTEM_PROMPT,
  greeting_text: DEFAULT_GREETING,
  voice_en: 'en_US-lessac-medium',
  voice_hi: 'hi_IN-priyamvada-medium',
  // Dedicated Customer Phone Number (DID)
  phone_number: null as string | null,
  phone_number_status: 'none',
  phone_number_price: 4.99,
  phone_number_country: 'US',
  // Human Handoff
  handoff_enabled: false,
  handoff_extension: '1001',
  handoff_fallback_threshold: 2,
  handoff_message: 'Please hold while I transfer you to a human agent.',
  handoff_message_hi: 'कृपया प्रतीक्षा करें, मैं आपकी कॉल मानव एजेंट को ट्रांसफर कर रहा हूँ।',
  // A/B Testing
  ab_testing_enabled: false,
  ab_variant_b_prompt: '',
  ab_variant_b_greeting: '',
  ab_variant_b_voice_en: 'en_US-lessac-medium',
  ab_variant_b_voice_hi: 'hi_IN-priyamvada-medium',
  ab_variant_b_llm_model: 'llama3.2:3b-instruct-q4_K_M',
  ab_split_ratio: 50,
  // Dialogue Policy
  dialogue_policy_enabled: false,
  dialogue_slots_json: '[]',
  // Multilingual Routing
  multilingual_routing: true,
  lang_confidence_threshold: 0.65,
  fallback_language: 'en',
  supported_languages: 'en,hi',
  // Google Sheets / Webhook Tools
  tools_enabled: false,
  tools_webhook_url: '',
  // Voice Cloning
  voice_cloning_enabled: false,
  cloned_voice_sample_path: null as string | null,
  // Speculative Response Generation
  speculative_generation_enabled: true,
  speculative_branch_count: 2,
}

export function AgentBuilder() {
  const { id } = useParams()
  const isNew = !id || id === 'new'
  const navigate = useNavigate()
  const { show } = useToast()
  const [activeTab, setActiveTab] = useState<TabKey>('setup')
  const [options, setOptions] = useState<Options | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [docs, setDocs] = useState<DocumentMeta[]>([])
  const [status, setStatus] = useState('draft')
  const [saving, setSaving] = useState(false)
  const [agentId, setAgentId] = useState<string | null>(isNew ? null : id!)
  const [abStats, setAbStats] = useState<Record<string, { count: number; avg_duration: number; handoffs: number }> | null>(null)
  const [testingOpen, setTestingOpen] = useState(false)
  const [testingWebhook, setTestingWebhook] = useState(false)
  const [webhookTestResult, setWebhookTestResult] = useState<{ ok: boolean; message: string; slots?: string[] } | null>(null)

  // Voice Sample Audio Preview
  const [playingVoice, setPlayingVoice] = useState<string | null>(null)
  const audioPreviewRef = useRef<HTMLAudioElement | null>(null)

  // Voice Cloning State & Audio Player
  const [uploadingVoiceClone, setUploadingVoiceClone] = useState(false)
  const [previewingVoiceClone, setPreviewingVoiceClone] = useState(false)
  const [playingVoiceCloneSample, setPlayingVoiceCloneSample] = useState(false)
  const voiceCloneAudioRef = useRef<HTMLAudioElement | null>(null)

  // Dedicated Phone Number (DID) State
  const [searchCountry, setSearchCountry] = useState('US')
  const [searchAreaCode, setSearchAreaCode] = useState('')
  const [availableNumbers, setAvailableNumbers] = useState<AvailablePhoneNumber[]>([])
  const [searchingNumbers, setSearchingNumbers] = useState(false)
  const [buyingNumber, setBuyingNumber] = useState<string | null>(null)
  const [phonePricing, setPhonePricing] = useState<PhonePricing | null>(null)
  const [showNumberPicker, setShowNumberPicker] = useState(false)

  // New slot entry state
  const [newSlotName, setNewSlotName] = useState('')
  const [newSlotLabel, setNewSlotLabel] = useState('')
  const [newSlotPrompt, setNewSlotPrompt] = useState('')
  const [newSlotRequired, setNewSlotRequired] = useState(true)

  useEffect(() => {
    api.options().then((o) => {
      setOptions(o)
      if (isNew) {
        setForm((f) => ({
          ...f,
          system_prompt: f.system_prompt || o.default_system_prompt || DEFAULT_SYSTEM_PROMPT,
          extension: o.suggested_extension || f.extension || '2000',
        }))
      }
    }).catch(() => undefined)

    api.getPhonePricing().then(setPhonePricing).catch(() => undefined)
  }, [isNew])

  useEffect(() => {
    if (isNew || !id) return
    api
      .getAgent(id)
      .then((a) => {
        setForm({
          name: a.name,
          description: a.description || '',
          extension: a.extension,
          language: a.language,
          llm_model: a.llm_model,
          system_prompt: a.system_prompt || DEFAULT_SYSTEM_PROMPT,
          greeting_text: a.greeting_text || DEFAULT_GREETING,
          voice_en: a.voice_en,
          voice_hi: a.voice_hi,
          phone_number: a.phone_number ?? null,
          phone_number_status: a.phone_number_status ?? 'none',
          phone_number_price: a.phone_number_price ?? 4.99,
          phone_number_country: a.phone_number_country ?? 'US',
          handoff_enabled: a.handoff_enabled ?? false,
          handoff_extension: a.handoff_extension || '1001',
          handoff_fallback_threshold: a.handoff_fallback_threshold ?? 2,
          handoff_message: a.handoff_message || 'Please hold while I transfer you to a human agent.',
          handoff_message_hi: a.handoff_message_hi || 'कृपया प्रतीक्षा करें, मैं आपकी कॉल मानव एजेंट को ट्रांसफर कर रहा हूँ।',
          ab_testing_enabled: a.ab_testing_enabled ?? false,
          ab_variant_b_prompt: a.ab_variant_b_prompt || '',
          ab_variant_b_greeting: a.ab_variant_b_greeting || '',
          ab_variant_b_voice_en: a.ab_variant_b_voice_en || a.voice_en,
          ab_variant_b_voice_hi: a.ab_variant_b_voice_hi || a.voice_hi,
          ab_variant_b_llm_model: a.ab_variant_b_llm_model || a.llm_model,
          ab_split_ratio: a.ab_split_ratio ? (a.ab_split_ratio <= 1 ? Math.round(a.ab_split_ratio * 100) : a.ab_split_ratio) : 50,
          dialogue_policy_enabled: a.dialogue_policy_enabled ?? false,
          dialogue_slots_json: a.dialogue_slots_json || '[]',
          multilingual_routing: a.multilingual_routing ?? true,
          lang_confidence_threshold: a.lang_confidence_threshold ?? 0.65,
          fallback_language: a.fallback_language || 'en',
          supported_languages: a.supported_languages || 'en,hi',
          tools_enabled: a.tools_enabled ?? false,
          tools_webhook_url: a.tools_webhook_url || '',
          voice_cloning_enabled: a.voice_cloning_enabled ?? false,
          cloned_voice_sample_path: a.cloned_voice_sample_path ?? null,
          speculative_generation_enabled: a.speculative_generation_enabled ?? false,
          speculative_branch_count: a.speculative_branch_count ?? 3,
        })
        setStatus(a.status)
        setAgentId(a.id)

        if (a.ab_testing_enabled) {
          api.getAbStats(a.id).then(setAbStats).catch(() => undefined)
        }
      })
      .catch((e) => show(e.message, true))
    api.listDocuments(id).then(setDocs).catch(() => undefined)
  }, [id, isNew, show])

  async function handleSearchNumbers() {
    setSearchingNumbers(true)
    try {
      const res = await api.searchPhoneNumbers(searchCountry, searchAreaCode || undefined)
      setAvailableNumbers(res)
      if (res.length === 0) {
        show('No phone numbers found for this criteria. Try another country or area code.', true)
      }
    } catch (err) {
      show(`Number search failed: ${(err as Error).message}`, true)
    } finally {
      setSearchingNumbers(false)
    }
  }

  async function handleBuyNumber(num: AvailablePhoneNumber) {
    if (!agentId) {
      show('Please save your agent first before purchasing a phone number.', true)
      return
    }
    setBuyingNumber(num.phone_number)
    try {
      const res = await api.buyPhoneNumber(agentId, num.phone_number, num.country_code)
      setForm((f) => ({
        ...f,
        phone_number: res.phone_number,
        phone_number_status: 'active',
        phone_number_price: num.monthly_price,
        phone_number_country: num.country_code,
      }))
      setShowNumberPicker(false)
      show(`🎉 Number ${num.phone_number} activated! Give this number to your customers to call your agent.`)
    } catch (err) {
      show(`Purchase failed: ${(err as Error).message}`, true)
    } finally {
      setBuyingNumber(null)
    }
  }

  async function handleReleaseNumber() {
    if (!agentId) return
    if (!window.confirm(`Release phone number ${form.phone_number}? Incoming customer calls to this number will no longer reach this agent.`)) return
    try {
      await api.releasePhoneNumber(agentId)
      setForm((f) => ({
        ...f,
        phone_number: null,
        phone_number_status: 'none',
      }))
      show('Phone number released successfully.')
    } catch (err) {
      show(`Failed to release number: ${(err as Error).message}`, true)
    }
  }

  async function handleUploadVoiceClone(file: File) {
    if (!agentId) return
    setUploadingVoiceClone(true)
    try {
      const updated = await api.uploadVoiceClone(agentId, file)
      setForm((f) => ({
        ...f,
        voice_cloning_enabled: true,
        cloned_voice_sample_path: updated.cloned_voice_sample_path,
        voice_en: updated.voice_en || f.voice_en,
      }))
      show('Voice sample uploaded and processed successfully! Matched acoustic model.')
    } catch (err) {
      show(`Voice clone upload failed: ${(err as Error).message}`, true)
    } finally {
      setUploadingVoiceClone(false)
    }
  }

  async function handleDeleteVoiceClone() {
    if (!agentId) return
    if (!window.confirm('Are you sure you want to remove the cloned voice?')) return
    try {
      await api.deleteVoiceClone(agentId)
      setForm((f) => ({
        ...f,
        voice_cloning_enabled: false,
        cloned_voice_sample_path: null,
      }))
      show('Cloned voice removed.')
    } catch (err) {
      show(`Failed to remove cloned voice: ${(err as Error).message}`, true)
    }
  }

  function playVoiceCloneSample() {
    if (!agentId) return
    if (playingVoiceCloneSample) {
      if (voiceCloneAudioRef.current) {
        voiceCloneAudioRef.current.pause()
        voiceCloneAudioRef.current = null
      }
      setPlayingVoiceCloneSample(false)
      return
    }
    if (voiceCloneAudioRef.current) {
      voiceCloneAudioRef.current.pause()
    }
    const audio = new Audio(api.voiceCloneSampleUrl(agentId) + `?t=${Date.now()}`)
    voiceCloneAudioRef.current = audio
    setPlayingVoiceCloneSample(true)
    audio.play().catch((err) => {
      show(`Failed to play sample: ${err.message}`, true)
      setPlayingVoiceCloneSample(false)
    })
    audio.onended = () => {
      setPlayingVoiceCloneSample(false)
      voiceCloneAudioRef.current = null
    }
  }

  function playVoiceClonePreview() {
    if (!agentId) return
    if (previewingVoiceClone) {
      if (voiceCloneAudioRef.current) {
        voiceCloneAudioRef.current.pause()
        voiceCloneAudioRef.current = null
      }
      setPreviewingVoiceClone(false)
      return
    }
    if (voiceCloneAudioRef.current) {
      voiceCloneAudioRef.current.pause()
    }
    const audio = new Audio(api.voiceClonePreviewUrl(agentId, 'Hello! This is a real-time preview of your custom cloned voice persona.') + `&t=${Date.now()}`)
    voiceCloneAudioRef.current = audio
    setPreviewingVoiceClone(true)
    audio.play().catch((err) => {
      show(`Failed to preview cloned voice: ${err.message}`, true)
      setPreviewingVoiceClone(false)
    })
    audio.onended = () => {
      setPreviewingVoiceClone(false)
      voiceCloneAudioRef.current = null
    }
  }

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  // Voice Preview Player
  function playVoice(voiceId: string) {
    if (playingVoice === voiceId) {
      if (audioPreviewRef.current) {
        audioPreviewRef.current.pause()
        audioPreviewRef.current = null
      }
      setPlayingVoice(null)
      return
    }

    if (audioPreviewRef.current) {
      audioPreviewRef.current.pause()
    }

    const url = api.voiceSampleUrl(voiceId)
    const audio = new Audio(url)
    audioPreviewRef.current = audio
    setPlayingVoice(voiceId)

    audio.play().catch((err) => {
      show(`Audio sample failed: ${err.message}`, true)
      setPlayingVoice(null)
    })

    audio.onended = () => {
      setPlayingVoice(null)
      audioPreviewRef.current = null
    }
  }

  function insertVariable(variable: string) {
    set('system_prompt', form.system_prompt ? `${form.system_prompt} ${variable}` : variable)
  }

  // Parse slots
  let parsedSlots: SlotDef[] = []
  try {
    parsedSlots = JSON.parse(form.dialogue_slots_json || '[]')
    if (!Array.isArray(parsedSlots)) parsedSlots = []
  } catch {
    parsedSlots = []
  }

  function updateSlots(updated: SlotDef[]) {
    set('dialogue_slots_json', JSON.stringify(updated, null, 2))
  }

  function handleAddSlot() {
    if (!newSlotName.trim()) return
    const key = newSlotName.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_')
    const next: SlotDef = {
      name: key,
      label: newSlotLabel.trim() || key,
      required: newSlotRequired,
      prompt_question: newSlotPrompt.trim() || `Could you please share your ${key}?`,
    }
    updateSlots([...parsedSlots, next])
    setNewSlotName('')
    setNewSlotLabel('')
    setNewSlotPrompt('')
  }

  function handleRemoveSlot(index: number) {
    const updated = parsedSlots.filter((_, i) => i !== index)
    updateSlots(updated)
  }

  function handleLoadPresets() {
    updateSlots(DEFAULT_SLOTS_PRESET)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload = {
        ...form,
        name: form.name.trim(),
        extension: form.extension.trim() || '2000',
        system_prompt: form.system_prompt.trim() || options?.default_system_prompt || DEFAULT_SYSTEM_PROMPT,
        greeting_text: form.greeting_text.trim() || DEFAULT_GREETING,
        ab_split_ratio: Number(form.ab_split_ratio) || 50,
      }

      if (isNew || !agentId) {
        const created = await api.createAgent(payload)
        show('Agent created successfully!')
        navigate(`/agents/${created.id}`, { replace: true })
      } else {
        await api.updateAgent(agentId, payload)
        show('Agent configuration saved')
        if (form.ab_testing_enabled) {
          api.getAbStats(agentId).then(setAbStats).catch(() => undefined)
        }
      }
    } catch (err) {
      show((err as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  async function deploy() {
    if (!agentId) {
      show('Save the agent first', true)
      return
    }
    setSaving(true)
    try {
      const res = await api.deployAgent(agentId)
      setStatus(res.status)
      show(res.dial_hint || `Live on extension ${res.extension}`)
    } catch (err) {
      show((err as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  async function undeploy() {
    if (!agentId) return
    setSaving(true)
    try {
      const res = await api.undeployAgent(agentId)
      setStatus(res.status)
      show('Agent stopped')
    } catch (err) {
      show((err as Error).message, true)
    } finally {
      setSaving(false)
    }
  }

  async function onUpload(file: File | null) {
    if (!file || !agentId) {
      show('Save the agent before uploading documents', true)
      return
    }
    try {
      await api.uploadDocument(agentId, file)
      show('Document uploaded — indexing…')
      const refresh = () => api.listDocuments(agentId).then(setDocs)
      await refresh()
      window.setTimeout(refresh, 2500)
      window.setTimeout(refresh, 6000)
    } catch (err) {
      show((err as Error).message, true)
    }
  }

  async function removeDoc(docId: string) {
    try {
      await api.deleteDocument(docId)
      if (agentId) setDocs(await api.listDocuments(agentId))
    } catch (err) {
      show((err as Error).message, true)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{isNew ? 'Build agent' : 'Edit agent'}</h1>
          <p>Configure your voice agent identity, speech prompts, and telephony connection.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {!isNew && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setTestingOpen(true)}
              title="Test this agent live in your browser using microphone or text"
            >
              🎙️ Test Agent
            </button>
          )}
          {!isNew && (
            <span className={`chip ${status === 'deployed' ? 'ok' : 'warn'}`}>{status}</span>
          )}
        </div>
      </div>

      {/* Streamlined Tab Navigation: Only 3 focused tabs */}
      <nav className="tabs-nav">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab-btn ${activeTab === t.id ? 'active' : ''}`}
            onClick={() => setActiveTab(t.id)}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
            {t.id === 'knowledge' && docs.length > 0 && (
              <span className="chip muted" style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem' }}>
                {docs.length}
              </span>
            )}
            {t.id === 'advanced' && (form.handoff_enabled || form.ab_testing_enabled || form.dialogue_policy_enabled || form.tools_enabled) && (
              <span className="chip ok" style={{ fontSize: '0.65rem', padding: '0.1rem 0.35rem' }}>
                Active
              </span>
            )}
          </button>
        ))}
      </nav>

      <form className="panel panel-pad" onSubmit={onSubmit}>
        {/* Tab 1: Agent Setup (Everything you need to build & run an agent in one clean view) */}
        {activeTab === 'setup' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* Section A: Identity & Telephony */}
            <div>
              <h3 className="panel-title" style={{ marginBottom: '0.75rem' }}>Agent Identity</h3>
              <div className="form-grid">
                <label className="field">
                  Agent Name *
                  <input
                    required
                    value={form.name}
                    onChange={(e) => set('name', e.target.value)}
                    placeholder="e.g. Customer Support Concierge"
                  />
                </label>
                <label className="field">
                  Asterisk Extension *
                  <input
                    required
                    value={form.extension}
                    onChange={(e) => set('extension', e.target.value)}
                    placeholder="2000"
                  />
                </label>
                <label className="field full">
                  Description / Department (Optional)
                  <input
                    value={form.description}
                    onChange={(e) => set('description', e.target.value)}
                    placeholder="Handles customer tier-1 triage and account questions"
                  />
                </label>
              </div>
            </div>

            {/* Section A.2: Dedicated Customer Phone Number (DID) */}
            <div style={{ borderTop: '1px solid var(--line)', paddingTop: '1.25rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <h3 className="panel-title" style={{ margin: 0 }}>Customer Phone Number (DID)</h3>
                  <span className="chip" style={{ background: '#e0e7ff', color: '#3730a3', fontSize: '0.7rem', fontWeight: 600 }}>
                    {phonePricing ? `$${phonePricing.monthly_price}/mo` : '$4.99/mo'}
                  </span>
                </div>
                {form.phone_number && (
                  <span className="chip ok" style={{ fontSize: '0.75rem', fontWeight: 600 }}>
                    ● Inbound Active
                  </span>
                )}
              </div>

              {form.phone_number ? (
                <div style={{
                  padding: '1.25rem',
                  background: '#f0fdf4',
                  border: '1px solid #bbf7d0',
                  borderRadius: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.75rem',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
                    <div>
                      <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#166534', fontWeight: 600 }}>
                        Dedicated Public Phone Number
                      </div>
                      <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#14532d', fontFamily: 'monospace', letterSpacing: '0.03em' }}>
                        {form.phone_number}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost-dark"
                        onClick={() => {
                          navigator.clipboard.writeText(form.phone_number || '')
                          show(`Copied ${form.phone_number} to clipboard!`)
                        }}
                      >
                        📋 Copy Number
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={handleReleaseNumber}
                      >
                        Release Number
                      </button>
                    </div>
                  </div>
                  <p style={{ margin: 0, fontSize: '0.85rem', color: '#166534', lineHeight: 1.5 }}>
                    ✓ <strong>Live Inbound Line:</strong> Anyone calling this number will immediately speak to <strong>{form.name || 'this agent'}</strong>. Your agent can converse naturally, answer queries, and book appointments directly into your calendar.
                  </p>
                </div>
              ) : (
                <div style={{
                  padding: '1.25rem',
                  background: '#f8fafc',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '1rem',
                }}>
                  <div>
                    <h4 style={{ margin: '0 0 0.25rem', fontSize: '1rem', color: 'var(--ink)' }}>
                      Give your customers a real number to call
                    </h4>
                    <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--muted)', lineHeight: 1.4 }}>
                      Get a dedicated real phone number for this agent. Customers can call it from anywhere in the world to talk to the agent and book appointments 24/7.
                    </p>
                  </div>

                  {!showNumberPicker ? (
                    <div>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => {
                          setShowNumberPicker(true)
                          if (availableNumbers.length === 0) {
                            handleSearchNumbers()
                          }
                        }}
                      >
                        + Get Dedicated Number ({phonePricing ? `$${phonePricing.monthly_price}/mo` : '$4.99/mo'})
                      </button>
                    </div>
                  ) : (
                    <div style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '0.75rem',
                      paddingTop: '0.5rem',
                      borderTop: '1px dashed var(--line)',
                    }}>
                      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                        <label style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                          Country
                          <select
                            value={searchCountry}
                            onChange={(e) => setSearchCountry(e.target.value)}
                            style={{ padding: '0.4rem 0.6rem', borderRadius: 6, border: '1px solid var(--line)', background: 'var(--panel)' }}
                          >
                            <option value="US">🇺🇸 United States (+1)</option>
                            <option value="GB">🇬🇧 United Kingdom (+44)</option>
                            <option value="IN">🇮🇳 India (+91)</option>
                            <option value="CA">🇨🇦 Canada (+1)</option>
                          </select>
                        </label>
                        <label style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                          Area Code (Optional)
                          <input
                            type="text"
                            placeholder="e.g. 415 or 212"
                            value={searchAreaCode}
                            onChange={(e) => setSearchAreaCode(e.target.value)}
                            style={{ width: '120px', padding: '0.4rem 0.6rem', borderRadius: 6, border: '1px solid var(--line)', background: 'var(--panel)' }}
                          />
                        </label>
                        <button
                          type="button"
                          className="btn btn-ink btn-sm"
                          disabled={searchingNumbers}
                          onClick={handleSearchNumbers}
                        >
                          {searchingNumbers ? 'Searching…' : '🔍 Find Numbers'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost-dark btn-sm"
                          onClick={() => setShowNumberPicker(false)}
                        >
                          Cancel
                        </button>
                      </div>

                      {searchingNumbers && (
                        <div style={{ padding: '0.75rem', fontSize: '0.85rem', color: 'var(--muted)' }}>
                          Searching carrier inventory…
                        </div>
                      )}

                      {!searchingNumbers && availableNumbers.length > 0 && (
                        <div style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                          gap: '0.75rem',
                          marginTop: '0.5rem',
                        }}>
                          {availableNumbers.map((num) => (
                            <div
                              key={num.phone_number}
                              style={{
                                padding: '0.75rem 1rem',
                                border: '1px solid var(--line)',
                                borderRadius: 8,
                                background: 'var(--panel)',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center',
                              }}
                            >
                              <div>
                                <div style={{ fontWeight: 600, fontFamily: 'monospace', fontSize: '1rem', color: 'var(--ink)' }}>
                                  {num.national_format || num.phone_number}
                                </div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>
                                  {num.locality ? `${num.locality}, ` : ''}{num.region || num.country_code} • ${num.monthly_price}/mo
                                </div>
                              </div>
                              <button
                                type="button"
                                className="btn btn-primary btn-sm"
                                disabled={buyingNumber === num.phone_number}
                                onClick={() => handleBuyNumber(num)}
                              >
                                {buyingNumber === num.phone_number ? 'Activating…' : `Buy ($${num.monthly_price})`}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Section B: Speech & Voices */}
            <div style={{ borderTop: '1px solid var(--line)', paddingTop: '1.25rem' }}>
              <h3 className="panel-title" style={{ marginBottom: '0.75rem' }}>Voice & Spoken Language</h3>
              <div className="form-grid">
                <label className="field">
                  Default Spoken Language
                  <select value={form.language} onChange={(e) => set('language', e.target.value)}>
                    {(options?.languages || []).map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  LLM Intelligence Model
                  <select value={form.llm_model} onChange={(e) => set('llm_model', e.target.value)}>
                    {(options?.models || []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="field">
                  <label>English Neural Voice</label>
                  <div className="voice-select-group">
                    <select value={form.voice_en} onChange={(e) => set('voice_en', e.target.value)}>
                      {(options?.voices_en || []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className={`btn btn-sm ${playingVoice === form.voice_en ? 'btn-danger' : 'btn-ghost-dark'}`}
                      onClick={() => playVoice(form.voice_en)}
                      title="Audition voice sample"
                    >
                      {playingVoice === form.voice_en ? '⏹ Stop' : '▶ Preview'}
                    </button>
                  </div>
                </div>

                <div className="field">
                  <label>Hindi Neural Voice</label>
                  <div className="voice-select-group">
                    <select value={form.voice_hi} onChange={(e) => set('voice_hi', e.target.value)}>
                      {(options?.voices_hi || []).map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className={`btn btn-sm ${playingVoice === form.voice_hi ? 'btn-danger' : 'btn-ghost-dark'}`}
                      onClick={() => playVoice(form.voice_hi)}
                      title="Audition voice sample"
                    >
                      {playingVoice === form.voice_hi ? '⏹ Stop' : '▶ Preview'}
                    </button>
                  </div>
                </div>

                {form.voice_cloning_enabled && (
                  <div className="full" style={{ padding: '0.65rem 0.85rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, fontSize: '0.85rem', color: '#166534', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>🎙️ <strong>Custom Voice Cloning Active:</strong> Synthesizing with cloned acoustic timbre.</span>
                    <button
                      type="button"
                      className="btn btn-ghost-dark btn-sm"
                      onClick={() => setActiveTab('advanced')}
                    >
                      Manage Clone in Advanced Settings →
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Section C: Conversation Greeting & System Prompt */}
            <div style={{ borderTop: '1px solid var(--line)', paddingTop: '1.25rem' }}>
              <h3 className="panel-title" style={{ marginBottom: '0.75rem' }}>Conversation & Prompts</h3>
              <div className="form-grid">
                <label className="field full">
                  Opening Greeting (Spoken immediately when call connects) *
                  <input
                    required
                    value={form.greeting_text}
                    onChange={(e) => set('greeting_text', e.target.value)}
                    placeholder="Thank you for calling. How may I help you today?"
                  />
                </label>

                <div className="full">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                    <label className="field" style={{ margin: 0 }}>System Prompt Directives *</label>
                    {/* Dynamic Variable Chips */}
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--muted)', alignSelf: 'center', marginRight: '0.2rem' }}>Insert:</span>
                      {PROMPT_VARIABLES.map((v) => (
                        <button
                          key={v.value}
                          type="button"
                          className="variable-chip"
                          onClick={() => insertVariable(v.value)}
                          title={`Click to insert ${v.value}`}
                        >
                          {v.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <textarea
                    required
                    rows={8}
                    value={form.system_prompt}
                    onChange={(e) => set('system_prompt', e.target.value)}
                    style={{ width: '100%', minHeight: 160 }}
                    placeholder="Instructions for the agent..."
                  />
                </div>
              </div>

              <div style={{ marginTop: '1rem', padding: '0.85rem 1rem', background: '#f8faf9', borderRadius: 10, border: '1px solid var(--line)', fontSize: '0.85rem' }}>
                <strong>💡 Dialing Hint:</strong> When callers dial extension <span className="mono">{form.extension || '2000'}</span>, Asterisk immediately invokes AudioSocket and opens a 20ms full-duplex PCM channel with this agent.
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Knowledge Base (RAG) */}
        {activeTab === 'knowledge' && (
          <div>
            <h3 className="panel-title">Knowledge Documents (RAG)</h3>
            <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '0.9rem' }}>
              Upload company documents (PDF, DOCX, XLSX, TXT, MD). Indexed into an isolated vector collection and queried via speculative RAG during calls.
            </p>

            {!isNew && agentId ? (
              <>
                <label className="btn btn-ghost-dark" style={{ width: 'fit-content', marginBottom: '1rem' }}>
                  📁 Upload Document
                  <input
                    type="file"
                    hidden
                    accept=".pdf,.docx,.xlsx,.txt,.md"
                    onChange={(e) => onUpload(e.target.files?.[0] || null)}
                  />
                </label>

                <div className="docs-list">
                  {docs.length === 0 && <div className="empty">No documents uploaded yet. Upload a PDF, Word, or text file to equip this agent with knowledge.</div>}
                  {docs.map((d) => (
                    <div key={d.id} className="doc-row">
                      <div>
                        <strong>{d.filename}</strong>
                        <div className="meta-row" style={{ marginTop: '0.35rem' }}>
                          <span className={`chip ${d.status === 'indexed' ? 'ok' : d.status === 'failed' ? 'warn' : 'muted'}`}>
                            {d.status}
                          </span>
                          {d.chunk_count > 0 && <span className="chip muted">{d.chunk_count} chunks</span>}
                        </div>
                        {d.error && <div style={{ color: 'var(--danger)', fontSize: '0.8rem' }}>{d.error}</div>}
                      </div>
                      <button className="btn btn-danger btn-sm" type="button" onClick={() => removeDoc(d.id)}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty">Please create and save this agent first before uploading knowledge documents.</div>
            )}
          </div>
        )}

        {/* Tab 3: Advanced Settings (Handoff, Dialogue Slots, A/B Testing, Multilingual Routing) */}
        {activeTab === 'advanced' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* 1. Human Handoff Card */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>📞</span> Human Handoff & Escalation
                  </div>
                  <p className="feature-desc">
                    Forward unanswerable calls or caller requests to a live human operator via Asterisk dialplan forwarding.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.handoff_enabled}
                    onChange={(e) => set('handoff_enabled', e.target.checked)}
                  />
                  <span>{form.handoff_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.handoff_enabled && (
                <div className="form-grid" style={{ marginTop: '0.5rem' }}>
                  <label className="field">
                    Target Extension (Operator Desk Phone)
                    <input
                      required={form.handoff_enabled}
                      value={form.handoff_extension}
                      onChange={(e) => set('handoff_extension', e.target.value)}
                      placeholder="1001"
                    />
                  </label>
                  <label className="field">
                    Fallback Threshold (Consecutive Confused Turns)
                    <input
                      type="number"
                      min="1"
                      max="10"
                      required={form.handoff_enabled}
                      value={form.handoff_fallback_threshold}
                      onChange={(e) => set('handoff_fallback_threshold', parseInt(e.target.value) || 2)}
                    />
                  </label>
                  <label className="field full">
                    English Transfer Announcement
                    <input
                      required={form.handoff_enabled}
                      value={form.handoff_message}
                      onChange={(e) => set('handoff_message', e.target.value)}
                      placeholder="Please hold while I transfer you to a human agent."
                    />
                  </label>
                  <label className="field full">
                    Hindi Transfer Announcement
                    <input
                      required={form.handoff_enabled}
                      value={form.handoff_message_hi}
                      onChange={(e) => set('handoff_message_hi', e.target.value)}
                      placeholder="कृपया प्रतीक्षा करें, मैं आपकी कॉल मानव एजेंट को ट्रांसफर कर रहा हूँ।"
                    />
                  </label>
                </div>
              )}
            </div>

            {/* 2. Dialogue Policy & Structured Slot Filling */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>📋</span> Structured Slot Filling (Form Extraction)
                  </div>
                  <p className="feature-desc">
                    Collect caller details (name, phone number, intent, account ID) through turn-by-turn conversational extraction.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.dialogue_policy_enabled}
                    onChange={(e) => set('dialogue_policy_enabled', e.target.checked)}
                  />
                  <span>{form.dialogue_policy_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.dialogue_policy_enabled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', marginTop: '0.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>
                      Configured slots ({parsedSlots.length}):
                    </span>
                    <button
                      type="button"
                      className="btn btn-ghost-dark btn-sm"
                      onClick={handleLoadPresets}
                    >
                      Load Standard Preset Slots
                    </button>
                  </div>

                  <div className="slot-list">
                    {parsedSlots.length === 0 && (
                      <div style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>
                        No slots defined. Click &ldquo;Load Standard Preset Slots&rdquo; or add custom slots below.
                      </div>
                    )}
                    {parsedSlots.map((s, idx) => (
                      <div key={idx} className={`slot-tag ${s.required ? 'required' : ''}`}>
                        <span>{s.label} ({s.name})</span>
                        {s.required && <span style={{ color: 'var(--accent)', fontSize: '0.7rem' }}>*REQ</span>}
                        <button
                          type="button"
                          onClick={() => handleRemoveSlot(idx)}
                          style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', padding: '0 2px' }}
                          title="Remove slot"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>

                  {/* Add Custom Slot Row */}
                  <div style={{ marginTop: '0.5rem', padding: '0.85rem', background: '#f8faf9', borderRadius: 10, border: '1px dashed var(--line)' }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Add Custom Slot</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr auto auto', gap: '0.5rem', alignItems: 'flex-end' }}>
                      <label className="field" style={{ margin: 0 }}>
                        Slot Key
                        <input
                          value={newSlotName}
                          onChange={(e) => setNewSlotName(e.target.value)}
                          placeholder="e.g. account_num"
                          style={{ padding: '0.4rem 0.5rem', fontSize: '0.85rem' }}
                        />
                      </label>
                      <label className="field" style={{ margin: 0 }}>
                        Display Label
                        <input
                          value={newSlotLabel}
                          onChange={(e) => setNewSlotLabel(e.target.value)}
                          placeholder="e.g. Account Number"
                          style={{ padding: '0.4rem 0.5rem', fontSize: '0.85rem' }}
                        />
                      </label>
                      <label className="field" style={{ margin: 0 }}>
                        Question Prompt
                        <input
                          value={newSlotPrompt}
                          onChange={(e) => setNewSlotPrompt(e.target.value)}
                          placeholder="e.g. What is your account number?"
                          style={{ padding: '0.4rem 0.5rem', fontSize: '0.85rem' }}
                        />
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8rem', paddingBottom: '0.5rem' }}>
                        <input
                          type="checkbox"
                          checked={newSlotRequired}
                          onChange={(e) => setNewSlotRequired(e.target.checked)}
                        />
                        Required
                      </label>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={handleAddSlot}
                      >
                        Add
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 3. A/B Testing Experiments */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>🧪</span> A/B Prompt & Voice Experimentation
                  </div>
                  <p className="feature-desc">
                    Split incoming calls between Variant A (Control) and Variant B (Experiment) to evaluate caller satisfaction and handoffs.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.ab_testing_enabled}
                    onChange={(e) => set('ab_testing_enabled', e.target.checked)}
                  />
                  <span>{form.ab_testing_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.ab_testing_enabled && (
                <>
                  <div style={{ marginTop: '0.5rem', padding: '0.85rem', background: '#f8faf9', borderRadius: 10, border: '1px solid var(--line)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
                      <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Traffic Distribution</span>
                      <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span className="chip ab-badge-a">Variant A: {100 - form.ab_split_ratio}%</span>
                        <span className="chip ab-badge-b">Variant B: {form.ab_split_ratio}%</span>
                      </div>
                    </div>
                    <input
                      type="range"
                      min="5"
                      max="95"
                      step="5"
                      value={form.ab_split_ratio}
                      onChange={(e) => set('ab_split_ratio', parseInt(e.target.value) || 50)}
                      style={{ width: '100%', accentColor: 'var(--accent)' }}
                    />
                  </div>

                  {agentId && abStats && (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.5rem' }}>
                      <div style={{ padding: '0.85rem', borderRadius: 10, background: '#f0f9ff', border: '1px solid #bae6fd' }}>
                        <strong style={{ color: '#0369a1', fontSize: '0.9rem' }}>Variant A (Control)</strong>
                        <div style={{ fontSize: '0.85rem', marginTop: '0.4rem', display: 'flex', gap: '1.25rem' }}>
                          <div>Calls: <strong>{abStats.a?.count ?? 0}</strong></div>
                          <div>Avg Dur: <strong>{Math.round(abStats.a?.avg_duration ?? 0)}s</strong></div>
                          <div>Handoffs: <strong>{abStats.a?.handoffs ?? 0}</strong></div>
                        </div>
                      </div>
                      <div style={{ padding: '0.85rem', borderRadius: 10, background: '#fefce8', border: '1px solid #fde68a' }}>
                        <strong style={{ color: '#b45309', fontSize: '0.9rem' }}>Variant B (Experiment)</strong>
                        <div style={{ fontSize: '0.85rem', marginTop: '0.4rem', display: 'flex', gap: '1.25rem' }}>
                          <div>Calls: <strong>{abStats.b?.count ?? 0}</strong></div>
                          <div>Avg Dur: <strong>{Math.round(abStats.b?.avg_duration ?? 0)}s</strong></div>
                          <div>Handoffs: <strong>{abStats.b?.handoffs ?? 0}</strong></div>
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="form-grid" style={{ marginTop: '0.5rem' }}>
                    <label className="field">
                      Variant B LLM Model
                      <select value={form.ab_variant_b_llm_model} onChange={(e) => set('ab_variant_b_llm_model', e.target.value)}>
                        {(options?.models || []).map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="field">
                      <label>Variant B English Voice</label>
                      <div className="voice-select-group">
                        <select value={form.ab_variant_b_voice_en} onChange={(e) => set('ab_variant_b_voice_en', e.target.value)}>
                          {(options?.voices_en || []).map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.label}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className={`btn btn-sm ${playingVoice === form.ab_variant_b_voice_en ? 'btn-danger' : 'btn-ghost-dark'}`}
                          onClick={() => playVoice(form.ab_variant_b_voice_en)}
                          title="Audition voice sample"
                        >
                          {playingVoice === form.ab_variant_b_voice_en ? '⏹ Stop' : '▶ Preview'}
                        </button>
                      </div>
                    </div>
                    <label className="field full">
                      Variant B Greeting Text
                      <input
                        required={form.ab_testing_enabled}
                        value={form.ab_variant_b_greeting}
                        onChange={(e) => set('ab_variant_b_greeting', e.target.value)}
                        placeholder="Hello! Welcome to our automated service. What can I do for you today?"
                      />
                    </label>
                    <label className="field full">
                      Variant B System Prompt
                      <textarea
                        required={form.ab_testing_enabled}
                        rows={5}
                        value={form.ab_variant_b_prompt}
                        onChange={(e) => set('ab_variant_b_prompt', e.target.value)}
                        placeholder="Experimental prompt variation..."
                      />
                    </label>
                  </div>
                </>
              )}
            </div>

            {/* 4. Multilingual Routing Subcard */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>🌐</span> Dynamic Language Auto-Detection
                  </div>
                  <p className="feature-desc">
                    Auto-detects spoken language on incoming audio frames. Falls back safely if detector confidence is low.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.multilingual_routing}
                    onChange={(e) => set('multilingual_routing', e.target.checked)}
                  />
                  <span>{form.multilingual_routing ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.multilingual_routing && (
                <div className="form-grid" style={{ marginTop: '0.5rem' }}>
                  <label className="field">
                    Confidence Threshold ({Math.round(form.lang_confidence_threshold * 100)}%)
                    <input
                      type="range"
                      min="0.30"
                      max="0.95"
                      step="0.05"
                      value={form.lang_confidence_threshold}
                      onChange={(e) => set('lang_confidence_threshold', parseFloat(e.target.value))}
                      style={{ accentColor: 'var(--accent)' }}
                    />
                  </label>
                  <label className="field">
                    Fallback Language
                    <select value={form.fallback_language} onChange={(e) => set('fallback_language', e.target.value)}>
                      <option value="en">English (en)</option>
                      <option value="hi">Hindi (hi)</option>
                    </select>
                  </label>
                </div>
              )}
            </div>

            {/* 5. Google Sheets / Webhook Tools (Live Appointment Booking) */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>📅</span> Google Sheets / Webhook Tools (Live Appointment Booking)
                  </div>
                  <p className="feature-desc">
                    Enable your voice agent to dynamically check real-time appointment availability from a Google Spreadsheet and book caller slots live during the phone conversation.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.tools_enabled}
                    onChange={(e) => set('tools_enabled', e.target.checked)}
                  />
                  <span>{form.tools_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.tools_enabled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.75rem' }}>
                  <div className="field full" style={{ margin: 0 }}>
                    <label style={{ fontWeight: 600, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span>Google Apps Script Web App URL *</span>
                      <span style={{ fontSize: '0.75rem', fontWeight: 'normal', color: 'var(--muted)' }}>
                        Must accept GET (read availability) & POST (book slot)
                      </span>
                    </label>
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.35rem' }}>
                      <input
                        required={form.tools_enabled}
                        value={form.tools_webhook_url}
                        onChange={(e) => set('tools_webhook_url', e.target.value)}
                        placeholder="https://script.google.com/macros/s/AKfycbx.../exec"
                        style={{ flex: 1, fontFamily: 'monospace', fontSize: '0.85rem' }}
                      />
                      <button
                        type="button"
                        className="btn btn-ghost-dark btn-sm"
                        disabled={testingWebhook || !form.tools_webhook_url.trim()}
                        onClick={async () => {
                          setTestingWebhook(true)
                          setWebhookTestResult(null)
                          try {
                            const res = await api.testWebhook(form.tools_webhook_url.trim())
                            setWebhookTestResult(res)
                            if (res.ok) {
                              show('Webhook connection verified!')
                            } else {
                              show(`Webhook test failed: ${res.message}`, true)
                            }
                          } catch (err) {
                            setWebhookTestResult({ ok: false, message: (err as Error).message })
                            show(`Webhook test error: ${(err as Error).message}`, true)
                          } finally {
                            setTestingWebhook(false)
                          }
                        }}
                      >
                        {testingWebhook ? 'Testing…' : '🔌 Test Webhook'}
                      </button>
                    </div>
                  </div>

                  {webhookTestResult && (
                    <div
                      style={{
                        padding: '0.75rem 1rem',
                        borderRadius: 8,
                        fontSize: '0.85rem',
                        background: webhookTestResult.ok ? '#f0fdf4' : '#fef2f2',
                        border: `1px solid ${webhookTestResult.ok ? '#bbf7d0' : '#fecaca'}`,
                        color: webhookTestResult.ok ? '#166534' : '#991b1b',
                      }}
                    >
                      <strong>{webhookTestResult.ok ? '✓ Webhook Responded Successfully' : '✗ Webhook Error'}:</strong>{' '}
                      {webhookTestResult.message}
                      {Array.isArray(webhookTestResult.slots) && (
                        <div style={{ marginTop: '0.35rem', fontSize: '0.8rem' }}>
                          Available slots returned:{' '}
                          {webhookTestResult.slots.length > 0
                            ? webhookTestResult.slots.map((s: any) => (typeof s === 'string' ? s : `${s.date || ''} ${s.slot || ''}`)).join(', ')
                            : 'None found (sheet might be empty or all booked)'}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Setup Guide Box */}
                  <details
                    style={{
                      background: '#f8faf9',
                      border: '1px solid var(--line)',
                      borderRadius: 8,
                      padding: '0.75rem 1rem',
                      fontSize: '0.85rem',
                    }}
                  >
                    <summary style={{ fontWeight: 600, cursor: 'pointer', color: 'var(--ink)' }}>
                      📖 How to set up your free Google Sheet in 2 minutes (Click to expand)
                    </summary>
                    <div style={{ marginTop: '0.75rem', lineHeight: 1.6, color: 'var(--ink)' }}>
                      <ol style={{ paddingLeft: '1.25rem', margin: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        <li>
                          Create a new <strong>Google Spreadsheet</strong> with headers in Row 1:
                          <br />
                          <code style={{ background: '#e2e8e4', padding: '0.15rem 0.4rem', borderRadius: 4, fontSize: '0.8rem' }}>
                            Date | Slot | Status | Patient Name | Phone | Reason
                          </code>
                        </li>
                        <li>
                          Add some test rows (e.g. Date: <code>tomorrow</code> or <code>2026-09-21</code>, Slot: <code>10:00 AM</code>, Status: <code>available</code>).
                        </li>
                        <li>
                          In the top menu, click <strong>Extensions &gt; Apps Script</strong>.
                        </li>
                        <li>
                          Paste this code into the editor:
                          <pre
                            style={{
                              background: '#1e293b',
                              color: '#e2e8f0',
                              padding: '0.75rem',
                              borderRadius: 6,
                              overflowX: 'auto',
                              fontSize: '0.78rem',
                              marginTop: '0.35rem',
                            }}
                          >{`function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = sheet.getDataRange().getValues();
  var targetDate = (e && e.parameter && e.parameter.date) ? String(e.parameter.date).trim().toLowerCase() : "";
  var availableSlots = [];
  for (var i = 1; i < data.length; i++) {
    var rowDate = String(data[i][0]).trim().toLowerCase();
    var slot = String(data[i][1]).trim();
    var status = String(data[i][2]).trim().toLowerCase();
    if ((!targetDate || rowDate.indexOf(targetDate) !== -1 || targetDate.indexOf(rowDate) !== -1) && status === "available") {
      availableSlots.push({ date: data[i][0], slot: slot });
    }
  }
  return ContentService.createTextOutput(JSON.stringify({
    status: "success",
    available_slots: availableSlots
  })).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var body = JSON.parse(e.postData.contents);
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = sheet.getDataRange().getValues();
  var reqDate = String(body.date || "").trim().toLowerCase();
  var reqSlot = String(body.slot || "").trim().toLowerCase();
  for (var i = 1; i < data.length; i++) {
    var rowDate = String(data[i][0]).trim().toLowerCase();
    var rowSlot = String(data[i][1]).trim().toLowerCase();
    if ((rowDate.indexOf(reqDate) !== -1 || reqDate.indexOf(rowDate) !== -1) &&
        (rowSlot.indexOf(reqSlot) !== -1 || reqSlot.indexOf(rowSlot) !== -1)) {
      sheet.getRange(i + 1, 3).setValue("booked");
      sheet.getRange(i + 1, 4).setValue(body.name || "");
      sheet.getRange(i + 1, 5).setValue(body.phone || "");
      sheet.getRange(i + 1, 6).setValue(body.reason || "");
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Appointment confirmed",
        date: data[i][0],
        slot: data[i][1]
      })).setMimeType(ContentService.MimeType.JSON);
    }
  }
  return ContentService.createTextOutput(JSON.stringify({
    status: "error",
    message: "Slot unavailable or not found"
  })).setMimeType(ContentService.MimeType.JSON);
}`}</pre>
                        </li>
                        <li>
                          Click <strong>Deploy &gt; New Deployment</strong>, choose <strong>Web app</strong>, set <strong>Who has access: Anyone</strong>, click <strong>Deploy</strong>, and copy the Web App URL into the box above.
                        </li>
                      </ol>
                    </div>
                  </details>
                </div>
              )}
            </div>

            {/* 6. Speculative Multi-Branch Response Generation */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>⚡</span> Speculative Multi-Branch Response Generation (Near-Zero Latency)
                  </div>
                  <p className="feature-desc">
                    While the caller is still speaking (via partial STT), predict 2–3 high-probability completions and generate candidate LLM responses in parallel. Commits to the matching branch the millisecond VAD closes the turn, yielding ~0ms TTFT.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.speculative_generation_enabled}
                    onChange={(e) => set('speculative_generation_enabled', e.target.checked)}
                  />
                  <span>{form.speculative_generation_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.speculative_generation_enabled && (
                <div style={{ marginTop: '0.75rem', padding: '0.85rem', background: '#f8faf9', borderRadius: 10, border: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Speculative Parallel Branches</span>
                    <span className="chip ok">{form.speculative_branch_count} Parallel Candidate Streams</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="5"
                    step="1"
                    value={form.speculative_branch_count}
                    onChange={(e) => set('speculative_branch_count', parseInt(e.target.value) || 3)}
                    style={{ width: '100%', accentColor: 'var(--accent)' }}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--muted)', marginTop: '0.35rem' }}>
                    <span>1 (Single Speculation)</span>
                    <span>3 (Recommended)</span>
                    <span>5 (Maximum Coverage)</span>
                  </div>
                  <div style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: 'var(--muted)', lineHeight: 1.5 }}>
                    💡 <strong>How it works:</strong> As the caller says <em>&quot;I want to book an...&quot;</em>, branches predict <em>&quot;...appointment for tomorrow&quot;</em> and <em>&quot;...appointment with a doctor&quot;</em>. LLM tokens are pre-buffered before caller silence is reached.
                  </div>
                </div>
              )}
            </div>

            {/* 7. On-The-Fly Voice Cloning for Personas */}
            <div className="feature-card">
              <div className="feature-header">
                <div>
                  <div className="feature-title">
                    <span>🎙️</span> On-The-Fly Voice Cloning for Personas
                  </div>
                  <p className="feature-desc">
                    Upload a short 5–15 second reference voice sample (WAV or MP3) to clone any custom timbre, pitch, and prosody into a branded agent voice.
                  </p>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={form.voice_cloning_enabled}
                    onChange={(e) => set('voice_cloning_enabled', e.target.checked)}
                  />
                  <span>{form.voice_cloning_enabled ? 'Enabled' : 'Disabled'}</span>
                </label>
              </div>

              {form.voice_cloning_enabled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.75rem' }}>
                  {isNew || !agentId ? (
                    <div className="empty" style={{ fontSize: '0.85rem' }}>
                      Please save this agent first to enable reference audio uploading and voice cloning.
                    </div>
                  ) : (
                    <>
                      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                        <label className="btn btn-ghost-dark btn-sm" style={{ cursor: uploadingVoiceClone ? 'not-allowed' : 'pointer' }}>
                          {uploadingVoiceClone ? '⏳ Processing Audio…' : '📁 Upload Voice Sample (WAV / MP3)'}
                          <input
                            type="file"
                            hidden
                            accept=".wav,.mp3,.ogg,.flac"
                            disabled={uploadingVoiceClone}
                            onChange={(e) => {
                              const file = e.target.files?.[0]
                              if (file) handleUploadVoiceClone(file)
                            }}
                          />
                        </label>

                        {form.cloned_voice_sample_path && (
                          <>
                            <button
                              type="button"
                              className={`btn btn-sm ${playingVoiceCloneSample ? 'btn-danger' : 'btn-ghost-dark'}`}
                              onClick={playVoiceCloneSample}
                              title="Listen to uploaded reference sample"
                            >
                              {playingVoiceCloneSample ? '⏹ Stop Sample' : '▶ Play Reference Audio'}
                            </button>

                            <button
                              type="button"
                              className={`btn btn-sm ${previewingVoiceClone ? 'btn-danger' : 'btn-primary'}`}
                              onClick={playVoiceClonePreview}
                              title="Synthesize and listen to cloned voice"
                            >
                              {previewingVoiceClone ? '⏹ Stop Preview' : '✨ Test Cloned Voice'}
                            </button>

                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={handleDeleteVoiceClone}
                              title="Remove cloned voice"
                            >
                              🗑️ Remove
                            </button>
                          </>
                        )}
                      </div>

                      {form.cloned_voice_sample_path ? (
                        <div style={{ padding: '0.75rem 1rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, fontSize: '0.85rem', color: '#166534' }}>
                          <strong>✓ Voice Cloned Active:</strong> Sample configured at <span className="mono">{form.cloned_voice_sample_path}</span>. The acoustic timbre transfer engine will shape outbound speech to match this speaker.
                        </div>
                      ) : (
                        <div style={{ padding: '0.75rem 1rem', background: '#fefce8', border: '1px solid #fef08a', borderRadius: 8, fontSize: '0.85rem', color: '#854d0e' }}>
                          ⚠️ No voice sample uploaded yet. Upload a 5–15 second audio file of a person speaking clearly without background music.
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Persistent Form Actions Footer */}
        <div className="form-actions" style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--line)' }}>
          <button className="btn btn-ink" type="submit" disabled={saving}>
            {saving ? 'Saving…' : isNew ? 'Create agent' : 'Save changes'}
          </button>
          {!isNew && status !== 'deployed' && (
            <button className="btn btn-primary" type="button" disabled={saving} onClick={deploy}>
              Deploy to Phone Line
            </button>
          )}
          {!isNew && status === 'deployed' && (
            <button className="btn btn-ghost-dark" type="button" disabled={saving} onClick={undeploy}>
              Stop Line
            </button>
          )}
          {!isNew && (
            <button
              type="button"
              className="btn btn-ghost-dark"
              onClick={() => setTestingOpen(true)}
              title="Test agent in browser"
            >
              🎙️ Test Agent
            </button>
          )}
          <Link className="btn btn-ghost-dark" to="/agents">
            Back to Fleet
          </Link>
        </div>
      </form>

      {testingOpen && agentId && (
        <SimulatorModal
          agent={{ ...form, id: agentId, status } as any}
          onClose={() => setTestingOpen(false)}
        />
      )}
    </>
  )
}
