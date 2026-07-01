export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand-mark ${compact ? 'brand-mark--compact' : ''}`}>
      <span className="brand-mark__seal">研</span>
      <span>
        <strong>教育智研</strong>
        {!compact && <small>EDUSCI RESEARCH STUDIO</small>}
      </span>
    </div>
  )
}

