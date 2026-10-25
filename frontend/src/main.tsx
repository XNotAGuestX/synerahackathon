import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
// Fonts are bundled, not loaded from a third-party CDN (offline demos, no external requests).
import '@fontsource/dm-sans/400.css'
import '@fontsource/dm-sans/500.css'
import '@fontsource/dm-sans/600.css'
import '@fontsource/dm-sans/700.css'
import '@fontsource/dm-mono/400.css'
import '@fontsource/dm-mono/500.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import './styles/index.css'

type BoundaryProps = { children: ReactNode }
type BoundaryState = { message: string | null }

class Boundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { message: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { message: error.message }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack)
  }

  render() {
    if (this.state.message) {
      return <main className="boot-shell"><p role="alert" className="boot-error">{this.state.message}</p></main>
    }
    return this.props.children
  }
}

const root = document.getElementById('root')
if (!root) throw new Error('Missing #root')
createRoot(root).render(
  <Boundary>
    <App />
  </Boundary>,
)
