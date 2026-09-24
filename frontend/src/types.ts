export interface Asset { id: string; symbol: string; name: string; exchange?: string; currency?: string; options_supported?: boolean }
export interface Strategy { direction: string; direction_code: string; entry_low: number | null; entry_high: number | null; stop_loss: number | null; tp1: number | null; tp2: number | null; tp3: number | null; condition: string; timing?: string; confidence?: number }
export interface Report {
 asset: Asset; generated_at: string; timing?: string;
 quote: { price?: number; change_pct?: number; as_of?: string; session?: string };
 strategy: Strategy; completeness?: { score?: number; label?: string };
 summary: Record<string, string>;
 modules: { title: string; status: string; summary: string; details?: string[] }[];
 sources: { name: string; url?: string; status: string; as_of?: string }[];
 warnings: string[];
}
export interface LibraryStrategy { id: string; name: string; description?: string; version?: string; capabilities?: string[]; backtest_adapter?: { engine?: string }; source_url?:string; validation_status?:string; license_note?:string }
export interface Appearance { icon?: string | null; background?: string | null }
export interface Workspace extends Appearance { reports?: Record<string, Report> }
export interface Bootstrap { strategies: LibraryStrategy[]; daily_strategy_assets: Asset[]; workspace_settings: Workspace }
export interface KnowledgeStatus { state: string; source_count: number; chunk_count: number; segment_count?: number; duration_seconds?: number; query_count: number; indexed_at?: string; message?: string; source?: { id: string; title: string; url: string; language: string } }
export interface Citation { id: string; title: string; text: string; timestamp: string; start_seconds: number; end_seconds: number; url: string; score: number; source_id: string }
export interface KnowledgeAnswer { question: string; answer: string; confidence: 'low' | 'medium' | 'high'; citations: Citation[]; retrieval: { method: string; returned: number }; notice: string }
