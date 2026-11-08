import { Construction } from 'lucide-react'
import { Empty, PageHeader, Panel } from '../components/ui.jsx'

export default function Placeholder({ title, phase }) {
  return (
    <>
      <PageHeader title={title} />
      <Panel>
        <Empty icon={Construction} title="Not built yet">
          This page arrives in {phase}.
        </Empty>
      </Panel>
    </>
  )
}
