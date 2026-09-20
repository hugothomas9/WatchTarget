import React, { useEffect, useRef, useState } from 'react'

// Nom du bot Telegram (sans @) pour le Login Widget. À aligner avec @BotFather.
const TELEGRAM_BOT = 'WatchTargetBot'

// Bouton officiel « Connexion Telegram ». Injecte le script du widget ; à l'auth,
// Telegram appelle window.onTelegramAuth(user). Ne fonctionne qu'avec le domaine
// déclaré chez @BotFather (/setdomain) — donc actif en prod, pas en localhost.
function TelegramLogin({ onAuth }) {
  const ref = useRef(null)
  useEffect(() => {
    window.onTelegramAuth = (user) => onAuth(user)
    const s = document.createElement('script')
    s.async = true
    s.src = 'https://telegram.org/js/telegram-widget.js?22'
    s.setAttribute('data-telegram-login', TELEGRAM_BOT)
    s.setAttribute('data-size', 'medium')
    s.setAttribute('data-onauth', 'onTelegramAuth(user)')
    s.setAttribute('data-request-access', 'write')
    const node = ref.current
    node && node.appendChild(s)
    return () => { if (node) node.innerHTML = '' }
  }, [])
  return <span ref={ref} />
}

const PAGES = { opportunites: 'Opportunités', stock: 'Stock', cibles: 'Cibles', favoris: 'Favoris' }
const LIMIT = 2000  // limite serveur (db.get_watches) — affichée si atteinte
const eur = (v) => v == null ? '—' : Math.round(v).toLocaleString('fr-FR') + ' €'
const yen = (v) => v == null ? '—' : '¥' + Math.round(v).toLocaleString('fr-FR')

// largeur bornée des menus déroulants : un nom de marque très long ne doit PAS
// étirer le <select> sur toute la barre (option la plus large = largeur du select)
const _selStyle = { maxWidth: 200, flex: '0 0 auto' }

// Tranches de budget = prix d'ACHAT détaxé en € (ce que la montre coûte au Japon).
// Bornes [min, max[ : max exclusif côté serveur, donc une montre pile à 5 000 €
// n'apparaît que dans « 5 – 10 k€ », jamais dans deux tranches à la fois.
const BUDGETS = {
  '': { label: 'Tous' },
  'moins1k': { label: 'moins de 1 000 €', max: 1000 },
  '1a5k': { label: '1 000 – 5 000 €', min: 1000, max: 5000 },
  '5a10k': { label: '5 000 – 10 000 €', min: 5000, max: 10000 },
  'plus10k': { label: 'plus de 10 000 €', min: 10000 },
}

// Vue MOBILE : l'utilisateur type est debout dans une boutique au Japon, sur son
// téléphone — un tableau de 15 colonnes y est inutilisable. Sous 700px on bascule
// en cartes ; le desktop garde le tableau inchangé.
function useIsMobile() {
  const [m, setM] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 700px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 700px)')
    const on = e => setM(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return m
}

// Carte mobile : photo + identité + les 3 chiffres qui décident (détaxé, vendu
// réel, marge) — `enriched` = vue opportunités/cibles/favoris (métriques EW).
function CarteMontre({ w, onFav, isFav, enriched, onOpen }) {
  const px = w.ew_median_eur ?? w.median_eur
  const chiffre = { fontSize: 13 }
  return (
    <div style={{ border: '1px solid #e2e2e8', borderRadius: 10, padding: 10,
                  display: 'flex', gap: 10, cursor: 'pointer',
                  opacity: w.status === 'vendue' ? 0.45 : 1 }}
         onClick={e => { if (!e.target.closest('a,button')) onOpen(w) }}>
      {w.images?.[0]
        ? <img src={w.images[0]} alt="" loading="lazy"
               onError={e => { e.currentTarget.style.visibility = 'hidden' }}
               style={{ width: 72, height: 72, objectFit: 'cover',
                        borderRadius: 8, flex: '0 0 auto' }} />
        : <div style={{ width: 72, height: 72, background: '#f2f2f5',
                        borderRadius: 8, flex: '0 0 auto' }} />}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
          <b title={w.modele_original || w.modele}
             style={{ overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap' }}>
            {w.marque} {w.modele}
          </b>
          <FavStar uid={w.uid} isFav={isFav} onFav={onFav} />
        </div>
        <div style={{ color: '#666', fontSize: 12, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {w.reference} · {w.boutique}{w.etat ? ` · ${w.etat}` : ''}
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap',
                      alignItems: 'baseline' }}>
          {enriched ? (<>
            <span style={chiffre}>détaxé <b>{eur(w.prix_detaxe_eur)}</b></span>
            <span style={chiffre}>vendu <b>{px != null ? eur(px) : '—'}</b></span>
            {w.spread_eur != null &&
              <span style={{ color: '#0a7d2c', fontWeight: 700 }}>
                +{eur(w.spread_eur)}</span>}
            {w.ew_sales_12m != null &&
              <span style={{ color: '#888', fontSize: 12 }}>
                {w.ew_sales_12m} vte/an</span>}
          </>) : (<>
            <span style={chiffre}>{yen(w.prix_ttc)}</span>
            <span style={chiffre}>détaxé <b>{eur(w.prix_detaxe_eur)}</b></span>
          </>)}
        </div>
        <div style={{ marginTop: 6, fontSize: 13 }}>
          {w.status === 'vendue'
            ? <span style={{ color: '#b00020' }}>vendue</span>
            : <a href={w.url} target="_blank" rel="noreferrer">voir la fiche →</a>}
        </div>
      </div>
    </div>
  )
}

// étoile favori : pleine (dorée) si déjà en favori, creuse sinon. Transition douce.
function FavStar({ uid, isFav, onFav }) {
  return (
    <button onClick={() => onFav(uid)}
            title={isFav ? 'retirer des favoris' : 'ajouter aux favoris'}
            aria-pressed={isFav}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 20, lineHeight: 1, padding: 2,
              color: isFav ? '#f5a623' : '#ccc',
              transform: isFav ? 'scale(1.15)' : 'scale(1)',
              transition: 'color .18s ease, transform .18s ease',
            }}>
      {isFav ? '★' : '☆'}
    </button>
  )
}

function Row({ w, onFav, isFav, onOpen }) {
  return (
    <tr style={{ opacity: w.status === 'vendue' ? 0.45 : 1, cursor: 'pointer' }}
        onClick={e => { if (!e.target.closest('a,button')) onOpen(w) }}>
      <td><FavStar uid={w.uid} isFav={isFav} onFav={onFav} /></td>
      <td>{w.images?.[0]
        ? <img src={w.images[0]} alt="" loading="lazy"
               onError={e => { e.currentTarget.style.display = 'none' }}
               style={{ width: 46, height: 46, objectFit: 'cover' }} />
        : '—'}</td>
      <td>{w.boutique}</td>
      <td title={w.modele_original || w.description}>{w.marque} {w.modele}</td>
      <td>{w.reference}</td>
      <td>{w.date_ajout_site || '—'}</td>
      <td title={w.etat_original || w.etat}>{w.etat || '—'}</td>
      <td title={w.raw_accessoires} style={{ textAlign: 'center', color: '#0a7d2c' }}>✓</td>
      <td>{yen(w.prix_ttc)}</td>
      <td>{eur(w.prix_detaxe_eur)}</td>
      <td style={{ fontWeight: w.benef_min > 0 ? 700 : 400,
                   color: w.benef_min > 0 ? '#0a7d2c' : '#999' }}>
        {w.benef_min != null ? eur(w.benef_min) : '—'}</td>
      <td>{w.status === 'vendue'
        ? <span style={{ color: '#b00020' }}>vendue</span>
        : <a href={w.url} target="_blank" rel="noreferrer">voir</a>}</td>
    </tr>
  )
}

function OppRow({ w, onFav, isFav, onOpen }) {
  // lien EveryWatch : résultats de ventes RÉELLES pour la réf (auctionType=result)
  const ew = `https://everywatch.com/watch-listing?searchTerm=${encodeURIComponent(w.reference)}&auctionType=result`
  const wc = `https://watchcharts.com/watches?q=${encodeURIComponent(w.reference)}`
  return (
    <tr style={{ opacity: w.status === 'vendue' ? 0.45 : 1, cursor: 'pointer' }}
        onClick={e => { if (!e.target.closest('a,button')) onOpen(w) }}>
      <td><FavStar uid={w.uid} isFav={isFav} onFav={onFav} /></td>
      <td>{w.images?.[0]
        ? <img src={w.images[0]} alt="" loading="lazy"
               onError={e => { e.currentTarget.style.display = 'none' }}
               style={{ width: 46, height: 46, objectFit: 'cover' }} />
        : '—'}</td>
      <td>{w.boutique}</td>
      <td title={w.modele_original || w.description}>{w.marque} {w.modele}</td>
      <td>{w.reference}</td>
      <td>{eur(w.prix_detaxe_eur)}</td>
      <td title={w.ew_last_eur != null
        ? `dernière vente réelle observée${w.ew_last_sale ? ' (' + w.ew_last_sale + ')' : ''} · pour info, médiane des prix AFFICHÉS Chrono24 : ${eur(w.median_eur)}`
        : `pas encore de vente réelle récupérée · médiane des prix AFFICHÉS Chrono24 : ${eur(w.median_eur)} (P25 ${eur(w.p25_eur)} — P75 ${eur(w.p75_eur)})`}>
        {w.ew_last_eur != null ? (
          <span>
            {eur(w.ew_last_eur)}
            {w.ew_last_sale && <span style={{ color: '#888', fontSize: 12 }}> {w.ew_last_sale}</span>}
          </span>
        ) : '—'}</td>
      <td title={w.ew_median_eur != null
        ? `${w.ew_n_sales} vente(s) réelle(s) · P25 ${eur(w.ew_p25_eur)} — P75 ${eur(w.ew_p75_eur)}`
          + (w.ew_matched_by === 'variant-image' ? ` · variante exacte ${w.ew_variant} (matchée par photo)`
             : w.ew_matched_by === 'dial+material' ? ' · à cadran+matière identiques'
             : ' · toutes variantes de la réf confondues')
        : 'pas encore de ventes réelles récupérées (EveryWatch)'}>
        {w.ew_median_eur != null ? (
          <span>
            <b>{eur(w.ew_median_eur)}</b>
            <span style={{ color: '#888', fontSize: 12 }}> ×{w.ew_n_sales}</span>
            {w.ew_matched_by === 'variant-image' && <span title="variante exacte" style={{ color: '#0a7d2c' }}> ◎</span>}
          </span>
        ) : '—'}</td>
      <td>{w.n_annonces}</td>
      <td title={w.ew_liquidity != null
        ? `Liquidité EveryWatch : ${w.ew_sales_12m} vente(s) RÉELLE(S) sur 12 mois (fréquence de transaction). 10/10 = ≥10 ventes/an.`
        : (w.liquidity_score != null
           ? 'Liquidité WatchCharts (jours-pour-vendre) — secours, EveryWatch indispo'
           : 'pas encore de donnée de liquidité')}>
        {w.ew_liquidity != null ? (
          <span>
            <b style={{ color: w.ew_liquidity >= 6 ? '#0a7d2c' : w.ew_liquidity >= 3 ? '#c78500' : '#b00020' }}>
              {w.ew_liquidity}/10</b>
            <span style={{ color: '#888', fontSize: 12 }}> · {w.ew_sales_12m} vte/an</span>
          </span>
        ) : w.liquidity_score != null ? (
          <span>
            <b style={{ color: w.liquidity_score >= 7 ? '#0a7d2c' : w.liquidity_score >= 4 ? '#c78500' : '#b00020' }}>
              {w.liquidity_score}/10</b>
            <span style={{ color: '#888', fontSize: 12 }}> · {Math.round(w.wc_days_on_market)}j*</span>
          </span>
        ) : '—'}</td>
      <td title={w.wc_volatility_pct != null
        ? 'volatilité WatchCharts (variation du prix dans le temps)'
        : 'dispersion des annonces (P75−P25)/médiane — WatchCharts indispo'}>
        {w.wc_volatility_pct != null ? w.wc_volatility_pct + '%'
          : (w.volatilite_pct != null ? w.volatilite_pct + '%*' : '—')}</td>
      <td title={w.prix_ref_source === 'everywatch'
        ? 'calculé sur le prix VENDU réel (EveryWatch)'
        : 'calculé sur la médiane des prix affichés Chrono24 (pas encore de ventes réelles)'}
          style={{ fontWeight: 700, color: '#0a7d2c' }}>
        +{eur(w.spread_eur)}{w.prix_ref_source === 'everywatch' ? '' : '*'}</td>
      <td title={`si revente sur Chrono24 : médiane − commission 6,5% − détaxé (coûts : ${eur(w.couts_import_eur)}). Vente entre particuliers → lis le Spread brut.`}
          style={{ fontWeight: 600, color: w.marge_nette_eur > 0 ? '#0a7d2c' : '#b00020' }}>
        {w.marge_nette_eur != null ? (w.marge_nette_eur > 0 ? '+' : '') + eur(w.marge_nette_eur) : '—'}</td>
      <td title="marge BRUTE si tu prix au P25 (bas du marché) pour vendre vite"
          style={{ color: w.spread_p25_eur > 0 ? '#0a7d2c' : '#b00020' }}>
        {w.spread_p25_eur != null ? (w.spread_p25_eur > 0 ? '+' : '') + eur(w.spread_p25_eur) : '—'}</td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <a href={w.url} target="_blank" rel="noreferrer">fiche</a>{' · '}
        <a href={ew} target="_blank" rel="noreferrer" title="ventes réelles EveryWatch">EveryWatch</a>{' · '}
        <a href={wc} target="_blank" rel="noreferrer" title="liquidité / jours-pour-vendre WatchCharts">WC</a>
      </td>
    </tr>
  )
}

// Courbe d'évolution du prix (les points s'enregistrent à chaque changement de
// prix constaté en collecte). Vert = le prix a baissé depuis le 1er point (bon
// pour l'acheteur), rouge = il a monté.
function Sparkline({ uid }) {
  const [pts, setPts] = useState(null)
  useEffect(() => {
    fetch(`/api/historique/${encodeURIComponent(uid)}`)
      .then(r => r.json()).then(setPts).catch(() => setPts([]))
  }, [uid])
  if (!pts) return <span style={{ color: '#888', fontSize: 13 }}>chargement…</span>
  const vals = pts.map(p => p.prix_detaxe_eur ?? p.prix_ttc).filter(v => v != null)
  if (vals.length < 2) {
    return <span style={{ color: '#888', fontSize: 13 }}>
      pas encore de variation enregistrée — l'historique se construit à chaque collecte
    </span>
  }
  const w = 280, h = 60
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = (max - min) || 1
  const xy = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * (w - 4) + 2},${h - 6 - ((v - min) / span) * (h - 12)}`)
  const monte = vals[vals.length - 1] >= vals[0]
  return (
    <div>
      <svg width={w} height={h} style={{ display: 'block' }}>
        <polyline points={xy.join(' ')} fill="none"
                  stroke={monte ? '#b00020' : '#0a7d2c'} strokeWidth="2" />
      </svg>
      <div style={{ fontSize: 12, color: '#666' }}>
        {vals.length} points · min {eur(min)} · max {eur(max)} ·
        dernier <b>{eur(vals[vals.length - 1])}</b>
      </div>
    </div>
  )
}

// Fiche détaillée : tout ce qu'il faut pour décider, en un panneau — photos,
// état/accessoires, métriques de valeur, évolution du prix, liens.
function FicheMontre({ w, onClose }) {
  const [img, setImg] = useState(0)
  const imgs = (w.images || []).filter(Boolean)
  const px = w.ew_median_eur ?? w.median_eur
  const ew = `https://everywatch.com/watch-listing?searchTerm=${encodeURIComponent(w.reference)}&auctionType=result`
  const Ligne = ({ l, v, t }) => v
    ? <div style={{ fontSize: 14, margin: '2px 0' }} title={t}>
        <span style={{ color: '#888' }}>{l} : </span>{v}</div>
    : null
  const Metrique = ({ l, v, forte }) => v == null ? null
    : <div style={{ fontSize: 14 }}>
        <span style={{ color: '#888' }}>{l}</span><br />
        <b style={forte ? { color: '#0a7d2c', fontSize: 17 } : {}}>{v}</b>
      </div>
  return (
    <div onClick={onClose}
         style={{ position: 'fixed', inset: 0, background: 'rgba(20,20,28,.5)',
                  zIndex: 50, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', padding: 12 }}>
      <div onClick={e => e.stopPropagation()}
           style={{ background: '#fff', borderRadius: 12, maxWidth: 640,
                    width: '100%', maxHeight: '92vh', overflowY: 'auto',
                    padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 19 }} title={w.modele_original}>
            {w.marque} {w.modele}
          </h2>
          <button onClick={onClose} style={{ border: 'none', background: 'none',
                  fontSize: 22, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>
        {imgs.length > 0 && <>
          <img src={imgs[img]} alt=""
               style={{ width: '100%', height: 260, objectFit: 'contain',
                        background: '#f6f6f8', borderRadius: 8, marginTop: 10 }} />
          {imgs.length > 1 && (
            <div style={{ display: 'flex', gap: 6, marginTop: 6, overflowX: 'auto' }}>
              {imgs.map((u, i) => (
                <img key={i} src={u} alt="" onClick={() => setImg(i)}
                     style={{ width: 48, height: 48, objectFit: 'cover',
                              borderRadius: 6, cursor: 'pointer',
                              outline: i === img ? '2px solid #4a6cf7' : 'none' }} />
              ))}
            </div>
          )}
        </>}
        <div style={{ marginTop: 10 }}>
          <Ligne l="Référence" v={w.reference} />
          <Ligne l="Boutique" v={w.boutique} />
          <Ligne l="État" v={w.etat} t={w.etat_original} />
          <Ligne l="Accessoires" v={w.raw_accessoires} />
          <Ligne l="Année" v={w.annee} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))',
                      gap: 10, background: '#f7f7f9', borderRadius: 8,
                      padding: 10, marginTop: 10 }}>
          <Metrique l="Prix détaxé JP" v={eur(w.prix_detaxe_eur)} />
          <Metrique l="Vendu réel (EW)"
                    v={px != null ? `${eur(px)}${w.ew_n_sales ? ` ×${w.ew_n_sales}` : ''}` : null} />
          <Metrique l="Dernière vente"
                    v={w.ew_last_eur != null ? `${eur(w.ew_last_eur)} (${w.ew_last_sale || '—'})` : null} />
          <Metrique l="Liquidité"
                    v={w.ew_sales_12m != null ? `${w.ew_sales_12m} ventes/an` : null} />
          <Metrique l="Marge brute" forte
                    v={w.spread_eur != null ? `+${eur(w.spread_eur)}` : null} />
          <Metrique l="Net plateforme"
                    v={w.marge_nette_eur != null ? eur(w.marge_nette_eur) : null} />
        </div>
        <div style={{ marginTop: 12 }}>
          <b style={{ fontSize: 14 }}>Évolution du prix</b>
          <div style={{ marginTop: 4 }}><Sparkline uid={w.uid} /></div>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 14, fontSize: 14 }}>
          <a href={w.url} target="_blank" rel="noreferrer">Fiche boutique →</a>
          {w.reference &&
            <a href={ew} target="_blank" rel="noreferrer">Ventes réelles EveryWatch →</a>}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('cibles')
  const [rows, setRows] = useState([])
  const [marques, setMarques] = useState([])
  const [marque, setMarque] = useState('')
  const [familles, setFamilles] = useState([])
  const [famille, setFamille] = useState('')
  const [qInput, setQInput] = useState('')     // saisie recherche (immédiate)
  const [qDeb, setQDeb] = useState('')         // valeur débouncée envoyée à l'API
  const [prixMax, setPrixMax] = useState('')
  const [budget, setBudget] = useState('')     // clé dans BUDGETS ('' = toutes)
  const [margeMin, setMargeMin] = useState('')
  const [detail, setDetail] = useState(null)   // montre ouverte en fiche détaillée

  // recherche débouncée : on n'interroge pas l'API à chaque frappe
  useEffect(() => {
    const t = setTimeout(() => setQDeb(qInput.trim()), 350)
    return () => clearTimeout(t)
  }, [qInput])
  const [sort, setSort] = useState('benef')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  // Vendues MASQUÉES par défaut : les 2/3 du stock en base sont des montres
  // vendues ou retirées (historique de prix, tri des dispos) — les afficher
  // d'office noyait les montres réellement achetables. La case permet de les
  // ressortir, l'historique n'est pas perdu.
  const [dispoOnly, setDispoOnly] = useState(true)
  const [favUids, setFavUids] = useState(() => new Set())
  const [alertes, setAlertes] = useState([])
  const [nouvelleAlerte, setNouvelleAlerte] = useState('')
  const [me, setMe] = useState(null)   // utilisateur Telegram connecté (ou null)
  const mobile = useIsMobile()

  const loadMe = () =>
    fetch('/api/me').then(r => r.json()).then(d => setMe(d.user)).catch(() => {})
  useEffect(() => { loadMe() }, [])

  const onTelegramAuth = (user) => {
    fetch('/api/auth/telegram', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user),
    }).then(r => { if (!r.ok) throw new Error('auth refusée'); return r.json() })
      .then(() => { loadMe(); reload() })
      .catch(e => setError(String(e.message || e)))
  }
  const logout = () =>
    fetch('/api/logout', { method: 'POST' }).then(() => { setMe(null); reload() })

  useEffect(() => {
    fetch('/api/marques').then(r => r.json()).then(setMarques).catch(() => {})
  }, [])

  // alertes mots-clés (onglet Cibles)
  const loadAlertes = () =>
    fetch('/api/alertes').then(r => r.json()).then(setAlertes).catch(() => {})
  useEffect(() => { if (page === 'cibles') loadAlertes() }, [page])

  const ajouterAlerte = () => {
    const mots = nouvelleAlerte.trim()
    if (!mots) return
    fetch('/api/alertes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mots_cles: mots }),
    }).then(r => r.json()).then(() => {
      setNouvelleAlerte(''); loadAlertes(); reload()
    }).catch(e => setError(String(e)))
  }
  const supprimerAlerte = (id) => {
    fetch(`/api/alertes/${id}`, { method: 'DELETE' })
      .then(() => { loadAlertes(); reload() }).catch(e => setError(String(e)))
  }

  // ensemble des uid favoris → l'étoile est pleine partout (stock, opportunités…)
  const loadFavUids = () =>
    fetch('/api/favoris').then(r => r.json())
      .then(favs => setFavUids(new Set(favs.map(f => f.uid))))
      .catch(() => {})
  useEffect(() => { loadFavUids() }, [])

  // filtre Modèle INDÉPENDANT (Daytona, Seamaster…) : liste globale, resserrée
  // par la marque si une marque est choisie
  useEffect(() => {
    setFamille('')
    fetch('/api/modeles' + (marque ? `?marque=${encodeURIComponent(marque)}` : ''))
      .then(r => r.json()).then(setFamilles).catch(() => setFamilles([]))
  }, [marque])

  // un seul effet + AbortController : pas de double fetch ni de réponse
  // obsolète qui écrase la bonne (l'ancien couple d'effets page/sort le faisait)
  useEffect(() => {
    const ctrl = new AbortController()
    const s = page === 'stock' && sort === 'benef' ? 'date' : sort
    const triOpp = ['liquidite', 'net', 'volatilite'].includes(sort) ? sort : 'spread'
    // Tranche de budget → bornes envoyées au serveur. Sur « Opportunités », le
    // champ « Achat max € » reste utilisable pour resserrer : on garde alors la
    // borne la PLUS BASSE des deux, sinon un plafond saisi à la main serait
    // silencieusement ignoré par la tranche (ou l'inverse).
    const b = BUDGETS[budget] || {}
    const hauts = [b.max, prixMax ? Number(prixMax) : null].filter(v => v != null)
    const bornes = { ...(b.min != null ? { prix_min: b.min } : {}),
                     ...(hauts.length ? { prix_max: Math.min(...hauts) } : {}) }
    const qs = page === 'cibles'
      ? ''
      : page === 'favoris'
      ? '?' + new URLSearchParams({ sort: triOpp }).toString()
      : page === 'opportunites'
      ? '?' + new URLSearchParams({ marque, famille, sort: triOpp,
                                    ...(qDeb ? { q: qDeb } : {}),
                                    ...bornes,
                                    ...(margeMin ? { spread_min: margeMin } : {}) }).toString()
      : '?' + new URLSearchParams({ marque, famille, sort: s,
                                    ...(qDeb ? { q: qDeb } : {}),
                                    ...bornes,
                                    ...(page === 'stock' && dispoOnly ? { dispo: 1 } : {}) }).toString()
    setError('')
    fetch(`/api/${page}${qs}`, { signal: ctrl.signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setRows)
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctrl.abort()
  }, [page, marque, famille, sort, refresh, dispoOnly, qDeb, prixMax, margeMin, budget])

  const reload = () => setRefresh(n => n + 1)

  const fav = (uid) => {
    // maj optimiste : l'étoile réagit tout de suite (smooth), on confirme au retour
    setFavUids(prev => {
      const next = new Set(prev)
      next.has(uid) ? next.delete(uid) : next.add(uid)
      return next
    })
    fetch(`/api/favoris/${encodeURIComponent(uid)}`, { method: 'POST' })
      .then(r => r.json())
      .then(({ favorite }) => {
        setFavUids(prev => {
          const next = new Set(prev)
          favorite ? next.add(uid) : next.delete(uid)
          return next
        })
        // dans l'onglet Favoris, retirer une montre la fait disparaître de la liste
        if (page === 'favoris' && !favorite) {
          setRows(rows => rows.filter(w => w.uid !== uid))
        }
      })
      .catch(e => setError(String(e)))
  }

  const collecte = () => {
    setBusy(true); setError('')
    fetch('/api/collecte?mode=incremental', { method: 'POST' })
      .then(r => {
        if (r.status === 409) throw new Error('Une collecte est déjà en cours.')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(() => reload())
      .catch(e => setError(String(e.message || e)))
      .finally(() => setBusy(false))
  }

  return (
    <div style={{ fontFamily: 'system-ui', padding: 20, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    flexWrap: 'wrap', gap: 8 }}>
        <h1 style={{ margin: 0 }}>Montres JP — Arbitrage</h1>
        <div>
          {me
            ? <span style={{ fontSize: 14 }}>
                Connecté : <b>{me.first_name || me.username || me.telegram_id}</b>
                <button onClick={logout} style={{ marginLeft: 8 }}>Déconnexion</button>
              </span>
            : <TelegramLogin onAuth={onTelegramAuth} />}
        </div>
      </div>
      <nav style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center',
                    flexWrap: 'wrap' }}>
        {Object.entries(PAGES).map(([k, label]) => (
          <button key={k} onClick={() => { setPage(k); setSort(k === 'stock' ? 'date' : (k === 'opportunites' || k === 'favoris') ? 'spread' : 'benef') }}
            style={{ fontWeight: page === k ? 700 : 400 }}>{label}</button>
        ))}
        {page !== 'cibles' && <>
        <span style={{ marginLeft: 16, whiteSpace: 'nowrap' }}>Marque :</span>
        <select value={marque} onChange={e => setMarque(e.target.value)}
                style={_selStyle}>
          <option value="">Toutes</option>
          {marques.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <span style={{ whiteSpace: 'nowrap' }}>Modèle :</span>
        <select value={famille} onChange={e => setFamille(e.target.value)}
                style={_selStyle}>
          <option value="">Tous</option>
          {familles.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
        {(page === 'stock' || page === 'opportunites') && <>
          <span style={{ whiteSpace: 'nowrap' }}>Budget :</span>
          <select value={budget} onChange={e => setBudget(e.target.value)}
                  title="prix d'achat détaxé au Japon" style={_selStyle}>
            {Object.entries(BUDGETS).map(([k, b]) =>
              <option key={k} value={k}>{b.label}</option>)}
          </select>
        </>}
        {(page === 'stock' || page === 'opportunites') && (
          <input value={qInput} onChange={e => setQInput(e.target.value)}
                 placeholder="🔍 rechercher (réf, modèle…)"
                 style={{ flex: '1 1 150px', maxWidth: 220, padding: '4px 8px' }} />
        )}
        {page === 'opportunites' && <>
          <input value={prixMax} onChange={e => setPrixMax(e.target.value.replace(/[^0-9]/g, ''))}
                 placeholder="Achat max €" title="prix d'achat détaxé maximum"
                 style={{ width: 90, padding: '4px 8px' }} />
          <input value={margeMin} onChange={e => setMargeMin(e.target.value.replace(/[^0-9]/g, ''))}
                 placeholder="Marge min €" title="marge brute minimum"
                 style={{ width: 90, padding: '4px 8px' }} />
        </>}
        <span style={{ whiteSpace: 'nowrap' }}>Tri :</span>
        {(page === 'opportunites' || page === 'favoris') ? (
          <select value={['liquidite', 'net', 'volatilite'].includes(sort) ? sort : 'spread'}
                  onChange={e => setSort(e.target.value)} style={_selStyle}>
            <option value="spread">Spread brut (marge €)</option>
            <option value="liquidite">Liquidité (jours pour vendre)</option>
            <option value="net">Marge nette</option>
            <option value="volatilite">Volatilité (stabilité du prix)</option>
          </select>
        ) : (
          <select value={sort} onChange={e => setSort(e.target.value)} style={_selStyle}>
            <option value="benef">Bénéfice</option>
            <option value="date">Date d'ajout</option>
            <option value="prix">Prix croissant</option>
            <option value="prix_desc">Prix décroissant</option>
          </select>
        )}
        {page === 'stock' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={!dispoOnly}
                   onChange={e => setDispoOnly(!e.target.checked)} />
            Afficher les vendues
          </label>
        )}
        </>}
        <button onClick={collecte} disabled={busy} style={{ marginLeft: 'auto' }}>
          {busy ? 'Collecte…' : 'Lancer une collecte'}
        </button>
      </nav>
      {page === 'cibles' && (
        <div style={{ background: '#f7f7f9', border: '1px solid #e0e0e6', borderRadius: 8,
                      padding: 12, marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input value={nouvelleAlerte} onChange={e => setNouvelleAlerte(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter') ajouterAlerte() }}
                   placeholder="ex : rolex daytona 126506A"
                   style={{ flex: '1 1 260px', padding: '6px 8px' }} />
            <button onClick={ajouterAlerte}>+ Ajouter une alerte</button>
            <span style={{ color: '#666', fontSize: 12 }}>
              (tous les mots doivent être présents · alerte Telegram sur les nouveaux arrivages)
            </span>
          </div>
          {alertes.length > 0 && (
            <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {alertes.map(a => (
                <span key={a.id} style={{ background: '#fff', border: '1px solid #d0d0d8',
                        borderRadius: 16, padding: '3px 10px', fontSize: 13 }}>
                  🎯 {a.libelle || a.mots_cles}
                  <button onClick={() => supprimerAlerte(a.id)} title="supprimer"
                          style={{ border: 'none', background: 'none', cursor: 'pointer',
                                   color: '#b00020', marginLeft: 6 }}>✕</button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {error && <p style={{ color: '#b00020' }}>Erreur : {error}</p>}
      <p style={{ color: '#666', fontSize: 13 }}>
        {rows.length} montre(s){rows.length >= LIMIT ? ` (max affiché : ${LIMIT})` : ''}
      </p>
      {mobile ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {rows.map(w => (
            <CarteMontre key={w.uid} w={w} onFav={fav} isFav={favUids.has(w.uid)} onOpen={setDetail}
              enriched={page === 'opportunites' || page === 'favoris' || page === 'cibles'} />
          ))}
        </div>
      ) : (
      <table border="1" cellPadding="6" style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14 }}>
        {(page === 'opportunites' || page === 'favoris' || page === 'cibles') ? (
          <thead><tr style={{ background: '#f3f3f3' }}>
            <th>★</th><th>Photo</th><th>Boutique</th><th>Montre</th><th>Réf</th>
            <th>Détaxé JP</th>
            <th title="DERNIÈRE vente réelle observée (prix + date). Survol : médiane Chrono24 pour info">Dern. vente</th>
            <th title="médiane des prix RÉELLEMENT VENDUS (EveryWatch : enchères + dealers). ◎ = variante exacte matchée par photo">Vendu réel</th>
            <th title="nb d'annonces actives = liquidité">Annonces</th>
            <th title="note de liquidité /10 (10 = vend le plus vite) + jours-pour-vendre">Liquidité</th>
            <th title="volatilité WatchCharts (dans le temps) ; * = dispersion des annonces si WC indispo">Volat.</th>
            <th title="valeur marché − détaxé = TA marge en mode valise + vente entre particuliers. Basé sur le prix VENDU réel (EveryWatch) quand dispo, sinon * = prix affichés Chrono24">Spread brut</th>
            <th title="mode valise + revente via plateforme (commission 6,5% déduite). Basé sur la même valeur marché que le Spread">Net plateforme</th>
            <th title="marge brute en vendant au P25 (bas du marché) pour sortir vite">Vente rapide</th>
            <th>Liens</th>
          </tr></thead>
        ) : (
          <thead><tr style={{ background: '#f3f3f3' }}>
            <th>★</th><th>Photo</th><th>Boutique</th><th>Montre</th><th>Réf</th><th>Ajout</th>
            <th>État</th><th title="boîte + papiers">Set</th><th>Prix Japon</th>
            <th>Détaxé €</th><th>Bénéfice</th><th>Lien</th>
          </tr></thead>
        )}
        <tbody>{rows.map(w => (page === 'opportunites' || page === 'favoris' || page === 'cibles')
          ? <OppRow key={w.uid} w={w} onFav={fav} isFav={favUids.has(w.uid)} onOpen={setDetail} />
          : <Row key={w.uid} w={w} onFav={fav} isFav={favUids.has(w.uid)} onOpen={setDetail} />)}</tbody>
      </table>
      )}
      {rows.length === 0 && !error && (page === 'opportunites'
        ? <p>Aucune opportunité pour l'instant — lance un scan marché :
            <code> python -m backend.market_scan</code></p>
        : page === 'cibles'
        ? <p>Aucune montre ne correspond à tes alertes. Crée une alerte ci-dessus
            (ex « rolex daytona 126506A ») — tu seras aussi prévenu par Telegram.</p>
        : <p>Aucune montre — lance une collecte.</p>)}
      {detail && <FicheMontre w={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}
