export type Agent = {
  id: string
  name: string
  description: string
  extension: string
  language: string
  llm_model: string
  system_prompt: string
  greeting_text: string
  voice_en: string
  voice_hi: string
  status: string
  port: number | null
  // Dedicated Customer Phone Number (DID)
  phone_number?: string | null
  phone_number_status?: string
  phone_number_price?: number
  phone_number_country?: string
  // Human Handoff
  handoff_enabled: boolean
  handoff_extension: string
  handoff_fallback_threshold: number
  handoff_message: string
  handoff_message_hi: string
  // A/B Testing
  ab_testing_enabled: boolean
  ab_variant_b_prompt: string
  ab_variant_b_greeting: string
  ab_variant_b_voice_en: string
  ab_variant_b_voice_hi: string
  ab_variant_b_llm_model: string
  ab_split_ratio: number
  // Dialogue Policy
  dialogue_policy_enabled: boolean
  dialogue_slots_json: string
  // Multilingual Routing
  multilingual_routing: boolean
  lang_confidence_threshold: number
  fallback_language: string
  supported_languages: string
  // Google Sheets / Dynamic Tools
  tools_enabled: boolean
  tools_webhook_url: string
  // Voice Cloning
  voice_cloning_enabled: boolean
  cloned_voice_sample_path: string | null
  // Speculative Response Generation
  speculative_generation_enabled: boolean
  speculative_branch_count: number
  created_at: string
  updated_at: string
}

export type DocumentMeta = {
  id: string
  agent_id: string
  filename: string
  stored_path: string
  status: string
  chunk_count: number
  error: string
  created_at: string
}

export type CallSummary = {
  id: string
  agent_id: string
  agent_name?: string
  call_uuid: string
  caller_id: string
  started_at: string
  ended_at: string
  duration_s: number
  status: string
  transcript_preview: string
  ab_variant?: string
  handoff_to?: string
  slots_json?: string
  disposition?: string
  sentiment?: string
}

export type CallTurn = {
  id: string
  call_id: string
  role: string
  content: string
  language: string
  offset_s?: number
  created_at: string
}

export type LiveCall = {
  call_uuid: string
  call_id: string
  agent_id: string
  agent_name: string
  extension: string
  port: number
  caller_id: string
  started_at: string
  duration_s: number
  ab_variant: string
  status: string
}

export type CallerProfile = {
  phone_number: string
  name: string
  call_count: number
  last_call_at: string
  last_disposition: string
  last_sentiment: string
  sentiment_history_json: string
  past_summaries_json: string
  last_summary: string
  entities_json: string
  relative_time?: string
  topic?: string
  created_at: string
  updated_at: string
}

export type WallboardStatus = {
  system: {
    telephony_ready: boolean
    runtime_ready: boolean
    total_active_calls: number
    concurrent_capacity: number
    channel_occupancy_pct: number
  }
  sip_trunk: {
    host: string
    port: number
    protocol: string
    reachable: boolean
    codecs: string[]
    configured_endpoints: string[]
  }
  active_calls: LiveCall[]
  lines: {
    agent_id: string
    agent_name: string
    extension: string
    port: number
    listening: boolean
    active_calls: number
    llm_model: string
    language: string
    ab_testing: boolean
    dialogue_policy: boolean
  }[]
}

export type Campaign = {
  id: string
  name: string
  agent_id: string
  agent_name?: string
  agent_extension?: string
  status: 'draft' | 'running' | 'paused' | 'completed'
  concurrency_limit: number
  caller_id: string
  greeting_text?: string
  collect_fields?: string
  total_contacts: number
  completed_contacts: number
  successful_contacts: number
  failed_contacts: number
  stats?: {
    total: number
    completed: number
    successful: number
    failed: number
    pending: number
    dialing: number
    conversion_rate_pct: number
    progress_pct: number
  }
  created_at: string
  updated_at: string
}

export type CampaignContact = {
  id: string
  campaign_id: string
  phone: string
  name: string
  custom_variables_json: string
  collected_data_json?: string
  status: 'pending' | 'dialing' | 'connected' | 'completed' | 'failed'
  attempts: number
  call_uuid: string
  call_id: string
  disposition: string
  duration_s: number
  last_attempt_at: string
  created_at: string
}

export type Options = {
  languages: { id: string; label: string }[]
  models: { id: string; label: string }[]
  voices_en: { id: string; label: string }[]
  voices_hi: { id: string; label: string }[]
  default_system_prompt: string
  dialogue_slots_preset?: { name: string; label: string; required: boolean; prompt_question: string }[]
  suggested_extension?: string
}


async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {})
  const token = localStorage.getItem('cf_token')
  const userJson = localStorage.getItem('cf_user')
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (userJson) {
    try {
      const user = JSON.parse(userJson)
      if (user?.username) {
        headers.set('X-User-Username', user.username)
      }
    } catch {
      /* ignore */
    }
  }

  const res = await fetch(path, { ...init, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export const api = {
  stats: () => request<Record<string, number>>('/api/stats'),
  health: () => request<{ status: string; runtime_ready: boolean; live_lines: unknown[] }>('/api/health'),
  options: () => request<Options>('/api/options'),
  listAgents: () => request<Agent[]>('/api/agents'),
  getAgent: (id: string) => request<Agent>(`/api/agents/${id}`),
  createAgent: (body: Partial<Agent>) =>
    request<Agent>('/api/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateAgent: (id: string, body: Partial<Agent>) =>
    request<Agent>(`/api/agents/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteAgent: (id: string) => request<{ ok: boolean }>(`/api/agents/${id}`, { method: 'DELETE' }),
  deployAgent: (id: string) =>
    request<Agent & { dial_hint?: string; reload_hint?: string }>(`/api/agents/${id}/deploy`, {
      method: 'POST',
    }),
  undeployAgent: (id: string) =>
    request<Agent>(`/api/agents/${id}/undeploy`, { method: 'POST' }),
  listDocuments: (agentId: string) => request<DocumentMeta[]>(`/api/agents/${agentId}/documents`),
  uploadDocument: async (agentId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<DocumentMeta>(`/api/agents/${agentId}/documents`, { method: 'POST', body: fd })
  },
  deleteDocument: (docId: string) =>
    request<{ ok: boolean }>(`/api/documents/${docId}`, { method: 'DELETE' }),
  listCalls: (agentId?: string) =>
    request<CallSummary[]>(agentId ? `/api/calls?agent_id=${agentId}` : '/api/calls'),
  getCall: (id: string) =>
    request<CallSummary & { turns: CallTurn[]; agent_name: string }>(`/api/calls/${id}`),
  getAbStats: (agentId: string) =>
    request<Record<string, { count: number; avg_duration: number; handoffs: number }>>(
      `/api/agents/${agentId}/ab-stats`
    ),
  voiceSampleUrl: (voice: string, text: string = '') =>
    `/api/voice-sample?voice=${encodeURIComponent(voice)}${text ? `&text=${encodeURIComponent(text)}` : ''}`,
  callAudioUrl: (callId: string) => `/api/calls/${callId}/audio`,
  getWallboard: () => request<WallboardStatus>('/api/wallboard/status'),
  hangupLiveCall: (callUuid: string) =>
    request<{ ok: boolean; message: string }>(`/api/wallboard/calls/${callUuid}/hangup`, {
      method: 'POST',
    }),
  listCampaigns: () => request<Campaign[]>('/api/campaigns'),
  getCampaign: (id: string) => request<Campaign>(`/api/campaigns/${id}`),
  createCampaign: (body: Partial<Campaign> & { contacts?: { phone: string; name?: string }[] }) =>
    request<Campaign>('/api/campaigns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  updateCampaign: (id: string, body: Partial<Campaign>) =>
    request<Campaign>(`/api/campaigns/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  deleteCampaign: (id: string) => request<{ ok: boolean }>(`/api/campaigns/${id}`, { method: 'DELETE' }),
  listCampaignContacts: (campaignId: string, limit = 100, offset = 0, status?: string) =>
    request<CampaignContact[]>(
      `/api/campaigns/${campaignId}/contacts?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ''}`
    ),
  addCampaignContacts: (campaignId: string, contacts: { phone: string; name?: string }[]) =>
    request<{ added: number; stats: Record<string, number> }>(`/api/campaigns/${campaignId}/contacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contacts }),
    }),
  uploadCampaignCsv: async (campaignId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<{ added: number; stats: Record<string, number> }>(`/api/campaigns/${campaignId}/contacts/csv`, {
      method: 'POST',
      body: fd,
    })
  },
  startCampaign: (id: string) =>
    request<{ status: string; stats: Record<string, number> }>(`/api/campaigns/${id}/start`, { method: 'POST' }),
  pauseCampaign: (id: string) =>
    request<{ status: string; stats: Record<string, number> }>(`/api/campaigns/${id}/pause`, { method: 'POST' }),
  resetCampaign: (id: string) =>
    request<{ ok: boolean; stats: Record<string, number> }>(`/api/campaigns/${id}/reset`, { method: 'POST' }),
  exportCampaignCsvUrl: (id: string) => `/api/campaigns/${id}/export`,
  testWebhook: (url: string) =>
    request<{ ok: boolean; message: string; slots?: string[] }>(`/api/tools/test-webhook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  uploadVoiceClone: async (agentId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return request<Agent>(`/api/agents/${agentId}/voice-clone/upload`, { method: 'POST', body: fd })
  },
  deleteVoiceClone: (agentId: string) =>
    request<Agent>(`/api/agents/${agentId}/voice-clone`, { method: 'DELETE' }),
  voiceCloneSampleUrl: (agentId: string) => `/api/agents/${agentId}/voice-clone/sample`,
  voiceClonePreviewUrl: (agentId: string, text?: string) =>
    `/api/agents/${agentId}/voice-clone/preview${text ? `?text=${encodeURIComponent(text)}` : ''}`,
  listCallers: (limit = 100) => request<CallerProfile[]>(`/api/callers?limit=${limit}`),
  getCaller: (phone: string) => request<CallerProfile>(`/api/callers/${encodeURIComponent(phone)}`),
  deleteCaller: (phone: string) => request<{ ok: boolean }>(`/api/callers/${encodeURIComponent(phone)}`, { method: 'DELETE' }),

  // Phone Numbers (DIDs)
  getPhonePricing: () => request<PhonePricing>('/api/phone-numbers/pricing'),
  searchPhoneNumbers: (country = 'US', areaCode?: string, limit = 10) =>
    request<AvailablePhoneNumber[]>(
      `/api/phone-numbers/search?country=${encodeURIComponent(country)}${areaCode ? `&area_code=${encodeURIComponent(areaCode)}` : ''}&limit=${limit}`
    ),
  buyPhoneNumber: (agentId: string, phoneNumber: string, countryCode = 'US') =>
    request<{ ok: boolean; message: string; phone_number: string; agent: Agent }>(
      `/api/agents/${agentId}/phone-number/buy`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone_number: phoneNumber, country_code: countryCode }),
      }
    ),
  releasePhoneNumber: (agentId: string) =>
    request<{ ok: boolean; message: string; agent: Agent }>(`/api/agents/${agentId}/phone-number`, {
      method: 'DELETE',
    }),
}

export type AvailablePhoneNumber = {
  phone_number: string
  national_format: string
  country_code: string
  region: string
  locality: string
  monthly_price: number
  per_minute_price: number
  currency: string
  provider: string
}

export type PhonePricing = {
  monthly_price: number
  per_minute_price: number
  currency: string
  provider: string
  wholesale_estimate: {
    number_cost_monthly: number
    inbound_per_minute: number
  }
}


