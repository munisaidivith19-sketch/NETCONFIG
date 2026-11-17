import { Link } from 'react-router-dom'
import { MapPinOff } from 'lucide-react'
import { Empty, PageHeader, Panel } from '../components/ui.jsx'

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Panel>
        <Empty icon={MapPinOff} title="There is no page at this address"
          action={<Link className="btn primary" to="/">Go to the Overview</Link>}>
          Check the address, or use the navigation to find what you need.
        </Empty>
      </Panel>
    </>
  )
}
