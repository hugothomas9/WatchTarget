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

function Row({ w, onFav, isFav }) {
  return (
    <tr style={{ opacity: w.status === 'vendue' ? 0.45 : 1 }}>
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

function OppRow({ w, onFav, isFav }) {
  // lien EveryWatch : résultats de ventes RÉELLES pour la réf (auctionType=result)
  const ew = `https://everywatch.com/watch-listing?searchTerm=${encodeURIComponent(w.reference)}&auctionType=result`
  const wc = `https://watchcharts.com/watches?q=${encodeURIComponent(w.reference)}`
  return (
    <tr style={{ opacity: w.status === 'vendue' ? 0.45 : 1 }}>
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

export default function App() {
  const [page, setPage] = useState('cibles')
  const [rows, setRows] = useState([])
  const [marques, setMarques] = useState([])
  const [marque, setMarque] = useState('')
  const [familles, setFamilles] = useState([])
  const [famille, setFamille] = useState('')
  const [sort, setSort] = useState('benef')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [dispoOnly, setDispoOnly] = useState(false)
  const [favUids, setFavUids] = useState(() => new Set())
  const [alertes, setAlertes] = useState([])
  const [nouvelleAlerte, setNouvelleAlerte] = useState('')
  const [me, setMe] = useState(null)   // utilisateur Telegram connecté (ou null)

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

  // cascade Marque → Ligne : les familles dispo suivent la marque choisie
  useEffect(() => {
    setFamille('')
    if (!marque) { setFamilles([]); return }
    fetch(`/api/familles?marque=${encodeURIComponent(marque)}`)
      .then(r => r.json()).then(setFamilles).catch(() => setFamilles([]))
  }, [marque])

  // un seul effet + AbortController : pas de double fetch ni de réponse
  // obsolète qui écrase la bonne (l'ancien couple d'effets page/sort le faisait)
  useEffect(() => {
    const ctrl = new AbortController()
    const s = page === 'stock' && sort === 'benef' ? 'date' : sort
    const qs = page === 'cibles'
      ? ''
      : (page === 'opportunites' || page === 'favoris')
      ? '?' + new URLSearchParams({ marque, sort: ['liquidite', 'net', 'volatilite'].includes(sort) ? sort : 'spread' }).toString()
      : '?' + new URLSearchParams({ marque, famille, sort: s,
                                    ...(page === 'stock' && dispoOnly ? { dispo: 1 } : {}) }).toString()
    setError('')
    fetch(`/api/${page}${qs}`, { signal: ctrl.signal })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setRows)
      .catch(e => { if (e.name !== 'AbortError') setError(String(e.message || e)) })
    return () => ctrl.abort()
  }, [page, marque, famille, sort, refresh, dispoOnly])

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
        {familles.length > 0 && <>
          <span style={{ whiteSpace: 'nowrap' }}>Ligne :</span>
          <select value={famille} onChange={e => setFamille(e.target.value)}
                  style={_selStyle}>
            <option value="">Toutes</option>
            {familles.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
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
            <input type="checkbox" checked={dispoOnly}
                   onChange={e => setDispoOnly(e.target.checked)} />
            Dispo uniquement
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
          ? <OppRow key={w.uid} w={w} onFav={fav} isFav={favUids.has(w.uid)} />
          : <Row key={w.uid} w={w} onFav={fav} isFav={favUids.has(w.uid)} />)}</tbody>
      </table>
      {rows.length === 0 && !error && (page === 'opportunites'
        ? <p>Aucune opportunité pour l'instant — lance un scan marché :
            <code> python -m backend.market_scan</code></p>
        : page === 'cibles'
        ? <p>Aucune montre ne correspond à tes alertes. Crée une alerte ci-dessus
            (ex « rolex daytona 126506A ») — tu seras aussi prévenu par Telegram.</p>
        : <p>Aucune montre — lance une collecte.</p>)}
    </div>
  )
}
