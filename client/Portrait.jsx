import { useEffect, useState } from 'react'

export function Portrait({ actor, workspaceClient, size = '' }) {
  const [source, setSource] = useState(null)
  const slug = actor?.id?.replace('char.', '')
  useEffect(() => {
    let disposed = false
    let url
    if (!slug || slug === 'player') return
    workspaceClient.readBytes(`assets/portraits/${slug}/image.png`).then((bytes) => {
      if (disposed) return
      url = URL.createObjectURL(new Blob([bytes], { type: 'image/png' }))
      setSource({ slug, url })
    }).catch(() => {})
    return () => { disposed = true; if (url) URL.revokeObjectURL(url) }
  }, [slug, workspaceClient])
  return (
    <div className={`mythfall-portrait ${size}`} style={{ '--portrait-color': actor?.color ?? '#a69576' }}>
      {source?.slug === slug ? <img src={source.url} alt={actor.name} /> : <span aria-hidden="true">{actor?.name?.slice(0, 1) ?? 'M'}</span>}
    </div>
  )
}
