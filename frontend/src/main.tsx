import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import './styles.css'

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
      return <main className="app-shell"><p role="alert" className="boot-error">{this.state.message}</p></main>
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
