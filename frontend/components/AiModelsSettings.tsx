import { useEffect } from 'react'
import { Boxes, HardDrive, Plug, Sparkles } from 'lucide-react'
import { useFilm } from '../contexts/FilmContext'
import { ModelLibrary } from '../views/film/ModelLibrary'
import { InstalledModelsPanel } from '../views/film/ModelsPanel'
import { AiProviderSettings } from './AiProviderSettings'
import { OpenRouterSettings } from './OpenRouterSettings'

/**
 * Settings → AI Models: the one place to connect, configure and test every
 * model this app can use.
 *
 * It is deliberately not part of the filmmaking workflow. Wiring up a provider
 * or downloading weights is setup you do once, not a step in making a video, so
 * it belongs with the rest of the app's configuration.
 */
export function AiModelsSettings() {
  const { capabilities, refreshCapabilities } = useFilm()

  // Capabilities normally load when a storyboard opens; this screen can be the
  // first thing a user visits, so make sure they are there.
  useEffect(() => {
    if (!capabilities) void refreshCapabilities()
  }, [capabilities, refreshCapabilities])

  return (
    <div className="space-y-8">
      <Section
        icon={<Plug className="h-4 w-4 text-violet-400" />}
        title="Connect a text model"
        blurb="Powers the AI Director, Build Film with AI, storyboard generation and prompt refinement. Any one of these is enough — a local server keeps it entirely offline. Each card can test its own connection."
      >
        <OpenRouterSettings />
      </Section>

      <Section
        icon={<Sparkles className="h-4 w-4 text-violet-400" />}
        title="More providers"
        blurb="Claude, Grok and Gemini for text; fal, WaveSpeed and Replicate to render image and video in the cloud instead of on this machine."
      >
        <AiProviderSettings />
      </Section>

      <Section
        icon={<Boxes className="h-4 w-4 text-violet-400" />}
        title="Model Library"
        blurb="Every model this app can use — search, and download the ones that run here."
      >
        <ModelLibrary />
      </Section>

      <Section
        icon={<HardDrive className="h-4 w-4 text-violet-400" />}
        title="Installed on this computer"
        blurb="What this GPU can run, what is already downloaded, and the quality profiles that suit it."
      >
        <InstalledModelsPanel />
      </Section>
    </div>
  )
}

function Section({
  icon,
  title,
  blurb,
  children,
}: {
  icon: React.ReactNode
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <div>
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-sm font-semibold text-white">{title}</h3>
        </div>
        <p className="mt-1 text-xs text-zinc-500 leading-relaxed">{blurb}</p>
      </div>
      {children}
    </section>
  )
}
