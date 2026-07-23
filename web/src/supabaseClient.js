import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_ANON_KEY

// anon 키가 아직 안 들어갔으면(플레이스홀더) false → 설정 안내 화면 표시
export const hasKey = Boolean(url && key && !key.includes('여기에'))
export const supabase = hasKey ? createClient(url, key) : null
