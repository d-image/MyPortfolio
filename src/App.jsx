import { Canvas, useFrame } from '@react-three/fiber'
import {
  ContactShadows,
  Environment,
  Float,
  OrbitControls,
  Sparkles,
  Stars,
} from '@react-three/drei'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { navItems, portfolio } from './content'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function readResponse(response) {
  let data
  try {
    data = await response.json()
  } catch {
    throw new Error('The account service returned an invalid response.')
  }
  if (!response.ok) {
    const message = typeof data.detail === 'string'
      ? data.detail
      : 'Please check the information and try again.'
    throw new Error(message)
  }
  return data
}

function FloatingShape({ position, scale, color, speed = 1, geometry = 'sphere' }) {
  const ref = useRef(null)

  useFrame((state) => {
    const t = state.clock.getElapsedTime() * speed
    if (!ref.current) return
    ref.current.rotation.x = t * 0.35
    ref.current.rotation.y = t * 0.45
    ref.current.position.y = position[1] + Math.sin(t) * 0.18
  })

  const material = (
    <meshStandardMaterial
      color={color}
      metalness={0.35}
      roughness={0.15}
      emissive={color}
      emissiveIntensity={0.15}
    />
  )

  const geometryNode = {
    sphere: <sphereGeometry args={[1, 48, 48]} />,
    torus: <torusKnotGeometry args={[0.7, 0.24, 180, 24]} />,
    icosahedron: <icosahedronGeometry args={[0.95, 1]} />,
  }[geometry]

  return (
    <Float speed={1.5} rotationIntensity={0.7} floatIntensity={1.2}>
      <mesh ref={ref} position={position} scale={scale}>
        {geometryNode}
        {material}
      </mesh>
    </Float>
  )
}

function Scene() {
  const palette = useMemo(
    () => ['#7c3aed', '#22d3ee', '#f472b6', '#38bdf8', '#c084fc'],
    [],
  )

  return (
    <>
      <color attach="background" args={['#030014']} />
      <fog attach="fog" args={['#030014', 8, 18]} />
      <ambientLight intensity={1.3} />
      <directionalLight position={[3, 4, 2]} intensity={2.4} color="#ffffff" />
      <pointLight position={[-4, -2, 2]} intensity={24} color="#22d3ee" />
      <pointLight position={[4, 3, -2]} intensity={18} color="#7c3aed" />

      <Stars radius={100} depth={50} count={3500} factor={4} saturation={0} fade speed={1} />
      <Sparkles
        count={120}
        size={3}
        scale={[12, 8, 12]}
        speed={0.4}
        color={palette[1]}
      />

      <FloatingShape
        position={[-2.4, 0.8, 0]}
        scale={0.95}
        color={palette[0]}
        speed={0.8}
        geometry="icosahedron"
      />
      <FloatingShape
        position={[0, 0, 0]}
        scale={1.2}
        color={palette[1]}
        speed={1}
        geometry="torus"
      />
      <FloatingShape
        position={[2.4, -0.2, -0.4]}
        scale={0.7}
        color={palette[2]}
        speed={1.2}
        geometry="sphere"
      />

      <ContactShadows
        position={[0, -1.85, 0]}
        opacity={0.45}
        scale={14}
        blur={2.4}
        far={4.5}
      />
      <Environment preset="city" />
      <OrbitControls
        enablePan={false}
        enableZoom={false}
        minPolarAngle={Math.PI / 2.4}
        maxPolarAngle={Math.PI / 1.8}
        autoRotate
        autoRotateSpeed={0.45}
      />
    </>
  )
}

function Section({ eyebrow, title, children }) {
  return (
    <section className="panel">
      <div className="section-heading">
        <span>{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  )
}

function ScrollToTop() {
  const location = useLocation()

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [location.pathname])

  return null
}

function AppLayout({ children, user, onLogout, authError }) {
  const location = useLocation()
  const isBlogSection = ['/blog', '/login', '/signup'].includes(location.pathname)

  return (
    <div className="app-shell">
      <div className="canvas-shell">
        <Canvas camera={{ position: [0, 0.2, 6], fov: 48 }}>
          <Scene />
        </Canvas>
        <div className="canvas-overlay" />
      </div>

      <header className="topbar">
        <Link className="brand" to="/">
          {portfolio.name}
        </Link>
        <nav>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
              end={item.to === '/'}
            >
              {item.label}
            </NavLink>
          ))}
          {isBlogSection && (user ? (
            <>
              <span className="nav-account">{user.displayName || user.email}</span>
              <button className="nav-button" type="button" onClick={onLogout}>
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="nav-link">Log in</NavLink>
              <NavLink to="/signup" className="nav-link">Sign up</NavLink>
            </>
          ))}
        </nav>
        {isBlogSection && authError && <p className="auth-nav-error" role="status">{authError}</p>}
      </header>

      <main className="content">{children}</main>

      <footer className="site-footer">
        <p>{portfolio.name}</p>
        <div className="footer-links">
          {portfolio.social.map((item) => (
            <a key={item.label} href={item.href} target="_blank" rel="noreferrer">
              {item.label}
            </a>
          ))}
        </div>
      </footer>
    </div>
  )
}

function PageHero({ eyebrow, title, description, primary, secondary }) {
  return (
    <section className="hero page-hero">
      <div className="hero-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lede">{description}</p>
        {(primary || secondary) && (
          <div className="hero-actions">
            {primary}
            {secondary}
          </div>
        )}
      </div>

      <aside className="hero-card">
        <div className="glass-card">
          <span className="card-kicker">Snapshot</span>
          <h2>{portfolio.name}</h2>
          <p>{portfolio.location}</p>
          <div className="stat-grid">
            {portfolio.stats.map((stat) => (
              <div key={stat.label} className="stat-item">
                <strong>{stat.value}</strong>
                <span>{stat.label}</span>
              </div>
            ))}
          </div>
          <a className="text-link" href={portfolio.resume}>
            Resume Link
          </a>
        </div>
      </aside>
    </section>
  )
}

function HomePage() {
  return (
    <>
      <PageHero
        eyebrow={portfolio.role}
        title={portfolio.tagline}
        description={portfolio.about}
        primary={<Link className="button primary" to="/projects">View Projects</Link>}
        secondary={
          <a className="button secondary" href={`mailto:${portfolio.email}`}>
            Let&apos;s Talk
          </a>
        }
      />

      <Section eyebrow="Explore" title="Every section now has its own page">
        <div className="card-grid">
          {navItems
            .filter((item) => item.to !== '/')
            .map((item) => (
              <article key={item.to} className="glass-card project-card">
                <span className="card-kicker">Navigate</span>
                <h3>{item.label}</h3>
                <p>Open the dedicated {item.label.toLowerCase()} page with focused content.</p>
                <Link className="text-link" to={item.to}>
                  Visit page
                </Link>
              </article>
            ))}
        </div>
      </Section>
    </>
  )
}

function AboutPage() {
  return (
    <>
      <PageHero
        eyebrow="About"
        title="A portfolio starter with depth"
        description={portfolio.intro}
        primary={<Link className="button primary" to="/projects">See Projects</Link>}
      />

      <Section eyebrow="Skills" title="Tools and strengths">
        <div className="two-column">
          <p>{portfolio.about}</p>
          <div className="skill-cloud">
            {portfolio.skills.map((skill) => (
              <span key={skill}>{skill}</span>
            ))}
          </div>
        </div>
      </Section>

      <Section eyebrow="Services" title="How I can help">
        <div className="card-grid">
          {portfolio.services.map((service) => (
            <article key={service.title} className="glass-card project-card">
              <span className="card-kicker">Service</span>
              <h3>{service.title}</h3>
              <p>{service.description}</p>
            </article>
          ))}
        </div>
      </Section>
    </>
  )
}

function ProjectsPage() {
  return (
    <>
      <PageHero
        eyebrow="Projects"
        title="Featured work and case study starters"
        description="Each project lives here on its own section page, making the portfolio easier to browse and extend later with full case studies."
        primary={<Link className="button primary" to="/blog">Read the Blog</Link>}
      />

      <Section eyebrow="Selected Work" title="Project highlights">
        <div className="card-grid">
          {portfolio.projects.map((project) => (
            <article key={project.title} className="glass-card project-card">
              <span className="card-kicker">{project.stack}</span>
              <h3>{project.title}</h3>
              <p>{project.description}</p>
            </article>
          ))}
        </div>
      </Section>
    </>
  )
}

function ExperiencePage() {
  return (
    <>
      <PageHero
        eyebrow="Experience"
        title="Experience that scales"
        description="Use this page for your career timeline, responsibilities, and impact. It is ready for quick editing now and can grow into a detailed resume page later."
        primary={<a className="button primary" href={portfolio.resume}>Download Resume</a>}
      />

      <Section eyebrow="Timeline" title="Recent roles">
        <div className="timeline">
          {portfolio.experience.map((item) => (
            <article key={item.period} className="timeline-item">
              <span>{item.period}</span>
              <h3>{item.title}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>
      </Section>
    </>
  )
}

function ContactPage() {
  return (
    <>
      <PageHero
        eyebrow="Contact"
        title="Let&apos;s build something memorable"
        description={portfolio.contactText}
        primary={
          <a className="button primary" href={`mailto:${portfolio.email}`}>
            Email Me
          </a>
        }
      />

      <Section eyebrow="Reach Out" title="Contact details">
        <div className="contact-grid">
          <article className="glass-card contact-card">
            <span className="card-kicker">Email</span>
            <h3>{portfolio.email}</h3>
            <p>Use this for project inquiries, collaborations, or freelance work.</p>
          </article>
          <article className="glass-card contact-card">
            <span className="card-kicker">Phone</span>
            <h3>{portfolio.phone}</h3>
            <p>Replace this placeholder with your direct contact number if you want it public.</p>
          </article>
          <article className="glass-card contact-card">
            <span className="card-kicker">Social</span>
            <h3>Find me online</h3>
            <div className="social-row">
              {portfolio.social.map((item) => (
                <a key={item.label} href={item.href} target="_blank" rel="noreferrer">
                  {item.label}
                </a>
              ))}
            </div>
          </article>
        </div>
      </Section>
    </>
  )
}

function BlogPage({ user }) {
  const [posts, setPosts] = useState([])
  const [postsError, setPostsError] = useState('')
  const [editor, setEditor] = useState(null)
  const [editorError, setEditorError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/posts`, { signal: controller.signal })
      .then(readResponse)
      .then((data) => {
        if (!controller.signal.aborted) {
          setPosts(data.posts)
          setPostsError('')
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPostsError('Published posts are unavailable. Please try again later.')
        }
      })
    return () => controller.abort()
  }, [])

  async function savePost(event) {
    event.preventDefault()
    setSaving(true)
    setEditorError('')
    try {
      const response = await readResponse(await fetch(
        `${API_BASE_URL}/api/posts${editor.id ? `/${editor.id}` : ''}`,
        {
          method: editor.id ? 'PUT' : 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: editor.title,
            excerpt: editor.excerpt,
            content: editor.content,
          }),
        },
      ))
      setPosts((current) => editor.id
        ? current.map((post) => post.id === response.post.id ? response.post : post)
        : [response.post, ...current])
      setEditor(null)
    } catch (requestError) {
      setEditorError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to save the post.',
      )
    } finally {
      setSaving(false)
    }
  }

  async function deletePost(post) {
    if (!window.confirm(`Delete "${post.title}"? This cannot be undone.`)) return
    setPostsError('')
    try {
      await readResponse(await fetch(`${API_BASE_URL}/api/posts/${post.id}`, {
        method: 'DELETE',
        credentials: 'include',
      }))
      setPosts((current) => current.filter((item) => item.id !== post.id))
      if (editor?.id === post.id) setEditor(null)
    } catch (requestError) {
      setPostsError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to delete the post.',
      )
    }
  }

  const displayedPosts = posts.length > 0
    ? posts
    : portfolio.blogPosts.map((post) => ({ ...post, isSample: true }))

  return (
    <>
      <PageHero
        eyebrow="Blog"
        title="Ideas and stories from the community"
        description="Read articles from blog authors, or sign in to share a post of your own."
        primary={user
          ? (
            <button
              className="button primary"
              onClick={() => {
                setEditor({ title: '', excerpt: '', content: '' })
                setEditorError('')
              }}
              type="button"
            >
              Write a post
            </button>
          )
          : <Link className="button primary" to="/signup">Create an account to post</Link>}
        secondary={<Link className="button secondary" to="/contact">Work Together</Link>}
      />

      <Section eyebrow="Published" title="Latest posts">
        {user && (
          <p className="auth-welcome" role="status">
            Signed in as {user.displayName || user.email}. Your posts are published immediately.
          </p>
        )}
        {postsError && <p className="form-error" role="alert">{postsError}</p>}
        {editor && (
          <form className="post-editor glass-card" onSubmit={savePost}>
            <h3>{editor.id ? 'Edit post' : 'Write a post'}</h3>
            <label htmlFor="post-title">Title</label>
            <input
              id="post-title"
              maxLength={120}
              minLength={3}
              onChange={(event) => setEditor({ ...editor, title: event.target.value })}
              required
              value={editor.title}
            />
            <label htmlFor="post-excerpt">Short summary</label>
            <textarea
              id="post-excerpt"
              maxLength={300}
              onChange={(event) => setEditor({ ...editor, excerpt: event.target.value })}
              required
              rows={2}
              value={editor.excerpt}
            />
            <label htmlFor="post-content">Article</label>
            <textarea
              id="post-content"
              maxLength={20_000}
              minLength={10}
              onChange={(event) => setEditor({ ...editor, content: event.target.value })}
              required
              rows={10}
              value={editor.content}
            />
            {editorError && <p className="form-error" role="alert">{editorError}</p>}
            <div className="hero-actions">
              <button className="button primary" disabled={saving} type="submit">
                {saving ? 'Saving…' : editor.id ? 'Save changes' : 'Publish post'}
              </button>
              <button
                className="button secondary"
                disabled={saving}
                onClick={() => setEditor(null)}
                type="button"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
        <div className="blog-list">
          {displayedPosts.map((post) => (
            <article key={post.id || post.title} className="glass-card blog-card">
              <div className="blog-meta">
                <span>{post.author || post.category}</span>
                <span>{post.createdAt ? new Date(post.createdAt).toLocaleDateString() : post.date}</span>
                {post.isMine && <span>Your post</span>}
              </div>
              <h3>{post.title}</h3>
              <p>{post.excerpt}</p>
              {post.content
                ? (
                  <details className="post-article">
                    <summary className="text-link">Read article</summary>
                    <p className="post-content">{post.content}</p>
                  </details>
                )
                : <span className="text-link">Sample article</span>}
              {post.isMine && (
                <div className="post-actions">
                  <button
                    className="text-link"
                    onClick={() => {
                      setEditor({
                        id: post.id,
                        title: post.title,
                        excerpt: post.excerpt,
                        content: post.content,
                      })
                      setEditorError('')
                    }}
                    type="button"
                  >
                    Edit
                  </button>
                  <button className="text-link" onClick={() => deletePost(post)} type="button">
                    Delete
                  </button>
                </div>
              )}
            </article>
          ))}
        </div>
      </Section>
    </>
  )
}

function AuthPage({ mode, user, onAuthenticated }) {
  const isSignup = mode === 'signup'
  const navigate = useNavigate()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const data = await readResponse(await fetch(
        `${API_BASE_URL}/api/auth/${isSignup ? 'signup' : 'login'}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, display_name: displayName }),
        },
      ))
      onAuthenticated(data.user)
      navigate('/blog')
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to reach the account service.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="auth-panel glass-card">
      <p className="eyebrow">Blog account</p>
      <h1>{isSignup ? 'Create your account' : 'Welcome back'}</h1>
      <p className="lede">
        {user
          ? `You are signed in as ${user.email}.`
          : isSignup
            ? 'Create an account to establish your identity on the blog.'
            : 'Log in to your blog account.'}
      </p>
      {user ? (
        <Link className="button primary" to="/blog">Continue to the blog</Link>
      ) : (
        <form className="auth-form" onSubmit={handleSubmit}>
          {isSignup && (
            <>
              <label htmlFor="auth-display-name">Display name</label>
              <input
                autoComplete="nickname"
                id="auth-display-name"
                maxLength={60}
                onChange={(event) => setDisplayName(event.target.value)}
                required
                value={displayName}
              />
            </>
          )}
          <label htmlFor="auth-email">Email</label>
          <input
            autoComplete="email"
            id="auth-email"
            maxLength={254}
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
          <label htmlFor="auth-password">Password</label>
          <input
            autoComplete={isSignup ? 'new-password' : 'current-password'}
            id="auth-password"
            maxLength={128}
            minLength={isSignup ? 12 : 1}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          {isSignup && <p className="form-hint">Use at least 12 characters.</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="button primary" disabled={busy} type="submit">
            {busy ? 'Please wait…' : isSignup ? 'Create account' : 'Log in'}
          </button>
        </form>
      )}
      {!user && (
        <p className="auth-switch">
          {isSignup ? 'Already have an account?' : 'New to the blog?'}{' '}
          <Link className="text-link" to={isSignup ? '/login' : '/signup'}>
            {isSignup ? 'Log in' : 'Create an account'}
          </Link>
        </p>
      )}
    </section>
  )
}

function NotFoundPage() {
  return (
    <section className="hero page-hero not-found">
      <div className="hero-copy">
        <p className="eyebrow">404</p>
        <h1>Page not found</h1>
        <p className="lede">The page you requested does not exist yet, but the rest of the portfolio is ready to explore.</p>
        <div className="hero-actions">
          <Link className="button primary" to="/">
            Back Home
          </Link>
        </div>
      </div>
    </section>
  )
}

export default function App() {
  const [user, setUser] = useState(null)
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_BASE_URL}/api/auth/me`, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 401) return null
        return readResponse(response)
      })
      .then((data) => {
        if (!controller.signal.aborted) {
          setUser(data?.user || null)
          setAuthError('')
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setAuthError('Account status is unavailable. Check the API connection.')
        }
      })
    return () => controller.abort()
  }, [])

  async function handleLogout() {
    setAuthError('')
    try {
      await readResponse(await fetch(`${API_BASE_URL}/api/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      }))
      setUser(null)
    } catch {
      setAuthError('Unable to log out. Please try again.')
    }
  }

  return (
    <AppLayout user={user} onLogout={handleLogout} authError={authError}>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/experience" element={<ExperiencePage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/blog" element={<BlogPage user={user} />} />
        <Route
          path="/signup"
          element={<AuthPage mode="signup" user={user} onAuthenticated={setUser} />}
        />
        <Route
          path="/login"
          element={<AuthPage mode="login" user={user} onAuthenticated={setUser} />}
        />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppLayout>
  )
}
