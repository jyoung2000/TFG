import { APP_NAME } from "../lib/brand";
import { useState } from 'react'
import { Clapperboard, FileVideo, Image as ImageIcon, Layers, Plus, Folder, MoreVertical, Trash2, Pencil, Sparkles, Zap, History } from 'lucide-react'
import { useProjects } from '../contexts/ProjectContext'
import { LtxLogo } from '../components/LtxLogo'
import { Button } from '../components/ui/button'
import type { Project, ProjectTab } from '../types/project'

const GETTING_STARTED_KEY = 'ltx-getting-started'

function formatDate(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric', 
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function ProjectCard({ project, onOpen, onDelete, onRename }: {
  project: Project
  onOpen: () => void
  onDelete: () => void
  onRename: () => void
}) {
  const [showMenu, setShowMenu] = useState(false)
  const [imgError, setImgError] = useState(false)
  
  // Get thumbnail: use stored thumbnail, or first asset's URL as fallback
  const thumbnailUrl = project.thumbnail || (project.assets.length > 0 ? project.assets[0].url : null)
  // For videos, try to find the first image asset for a better thumbnail
  const bestThumbnail = project.assets.find(a => a.type === 'image')?.url || thumbnailUrl
  
  return (
    <div 
      className="group relative bg-zinc-900 rounded-lg overflow-hidden border border-zinc-800 hover:border-zinc-700 transition-colors cursor-pointer"
      onClick={onOpen}
    >
      {/* Thumbnail */}
      <div className="aspect-video bg-zinc-800 flex items-center justify-center relative overflow-hidden">
        {bestThumbnail && !imgError ? (
          project.assets.find(a => a.type === 'video' && a.url === bestThumbnail) ? (
            <video 
              src={bestThumbnail} 
              className="w-full h-full object-cover" 
              muted 
              preload="metadata"
              onError={() => setImgError(true)}
            />
          ) : (
            <img 
              src={bestThumbnail} 
              alt={project.name} 
              className="w-full h-full object-cover" 
              onError={() => setImgError(true)}
            />
          )
        ) : (
          <Folder className="h-12 w-12 text-zinc-600" />
        )}
        {/* Hover overlay */}
        <div className="absolute inset-0 bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
      
      {/* Info */}
      <div className="p-3">
        <h3 className="font-medium text-white truncate">{project.name}</h3>
        <p className="text-xs text-zinc-500 mt-1">{formatDate(project.updatedAt)}</p>
      </div>
      
      {/* Menu button */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          setShowMenu(!showMenu)
        }}
        className="absolute top-2 right-2 p-1.5 rounded bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/70"
      >
        <MoreVertical className="h-4 w-4 text-white" />
      </button>
      
      {/* Dropdown menu */}
      {showMenu && (
        <div 
          className="absolute top-10 right-2 bg-zinc-800 rounded-lg shadow-lg border border-zinc-700 py-1 z-10 min-w-[120px]"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => { onRename(); setShowMenu(false) }}
            className="w-full px-3 py-2 text-left text-sm text-zinc-300 hover:bg-zinc-700 flex items-center gap-2"
          >
            <Pencil className="h-4 w-4" />
            Rename
          </button>
          <button
            onClick={() => { onDelete(); setShowMenu(false) }}
            className="w-full px-3 py-2 text-left text-sm text-red-400 hover:bg-zinc-700 flex items-center gap-2"
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </button>
        </div>
      )}
    </div>
  )
}

export function Home() {
  const { projects, createProject, deleteProject, renameProject, openProject, openPlayground, openQuickMode, openAnalyzeVideo } =
    useProjects()
  const { setCurrentView, openHistory, openTrain } = useProjects()
  const [isCreating, setIsCreating] = useState(false)
  const [createTarget, setCreateTarget] = useState<ProjectTab>('gen-space')
  const [newProjectName, setNewProjectName] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [showGettingStarted, setShowGettingStarted] = useState(() => {
    try {
      return localStorage.getItem(GETTING_STARTED_KEY) !== 'dismissed'
    } catch {
      return true
    }
  })

  const dismissGettingStarted = () => {
    setShowGettingStarted(false)
    try {
      localStorage.setItem(GETTING_STARTED_KEY, 'dismissed')
    } catch {
      // best effort
    }
  }

  const startCreate = (target: ProjectTab) => {
    setCreateTarget(target)
    setIsCreating(true)
  }

  const handleCreateProject = () => {
    if (newProjectName.trim()) {
      const project = createProject(newProjectName.trim())
      setNewProjectName('')
      setIsCreating(false)
      openProject(project.id, createTarget)
    }
  }
  
  const handleRenameProject = (id: string, currentName: string) => {
    setRenamingId(id)
    setRenameValue(currentName)
  }
  
  const submitRename = () => {
    if (renamingId && renameValue.trim()) {
      renameProject(renamingId, renameValue.trim())
    }
    setRenamingId(null)
    setRenameValue('')
  }
  
  return (
    <div className="h-screen bg-background flex">
      {/* Sidebar */}
      <aside className="w-64 border-r border-zinc-800 flex flex-col">
        <div className="p-6">
          <LtxLogo className="h-6 w-auto text-white" />
        </div>
        
        <nav className="flex-1 px-3">
          <button className="w-full px-3 py-2 rounded-lg bg-zinc-800 text-white text-left text-sm font-medium flex items-center gap-2">
            <Folder className="h-4 w-4" />
            Home
          </button>
          
          <div className="mt-6">
            <h4 className="px-3 text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
              Make
            </h4>
            {([
              { label: 'Create', hint: 'Quick video', icon: <Zap className="h-4 w-4" />, onClick: openQuickMode },
              { label: 'Reproduce image', hint: '', icon: <ImageIcon className="h-4 w-4" />, onClick: () => setCurrentView('analyze-image') },
              { label: 'Reproduce video', hint: '', icon: <FileVideo className="h-4 w-4" />, onClick: openAnalyzeVideo },
              { label: 'Train', hint: 'LoRA', icon: <Layers className="h-4 w-4" />, onClick: openTrain },
              { label: 'History', hint: '', icon: <History className="h-4 w-4" />, onClick: openHistory },
            ] as const).map(item => (
              <button
                key={item.label}
                onClick={item.onClick}
                className="w-full px-3 py-2 rounded-lg text-zinc-400 hover:bg-zinc-800 hover:text-white text-left text-sm flex items-center gap-2 transition-colors"
              >
                {item.icon}
                {item.label}
                {item.hint && <span className="ml-auto text-[10px] text-zinc-600" aria-hidden="true">{item.hint}</span>}
              </button>
            ))}
            <h4 className="px-3 mt-5 text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
              Advanced
            </h4>
            <button
              onClick={() => startCreate('storyboard')}
              className="w-full px-3 py-2 rounded-lg text-zinc-400 hover:bg-zinc-800 hover:text-white text-left text-sm flex items-center gap-2 transition-colors"
            >
              <Clapperboard className="h-4 w-4" />
              Film Studio
            </button>
            <button
              onClick={openPlayground}
              className="w-full px-3 py-2 rounded-lg text-zinc-400 hover:bg-zinc-800 hover:text-white text-left text-sm flex items-center gap-2 transition-colors"
            >
              <Sparkles className="h-4 w-4" />
              Playground
            </button>
          </div>
          
          {projects.length > 0 && (
            <div className="mt-6">
              <h4 className="px-3 text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
                Recent Projects
              </h4>
              {projects.slice(0, 5).map(project => (
                <button
                  key={project.id}
                  onClick={() => openProject(project.id)}
                  className="w-full px-3 py-2 rounded-lg text-zinc-400 hover:bg-zinc-800 hover:text-white text-left text-sm flex items-center gap-2 transition-colors truncate"
                >
                  <Folder className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{project.name}</span>
                </button>
              ))}
            </div>
          )}
        </nav>
        
        <div className="p-4 border-t border-zinc-800">
          <button
            onClick={() => startCreate('gen-space')}
            className="w-full px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Project
          </button>
        </div>
      </aside>
      
      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        {/* Header Banner with video background */}
        <div className="relative h-72 overflow-hidden">
          <video
            src="./hero-video.mp4"
            autoPlay
            loop
            muted
            playsInline
            className="absolute inset-0 w-full h-full object-cover"
          />
          {/* Dark overlay for text readability */}
          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/30 to-black/10" />
          <div className="absolute bottom-6 left-8 z-10">
            <h1 className="text-3xl font-bold text-white mb-2 drop-shadow-lg">{APP_NAME}</h1>
            <p className="text-zinc-200 drop-shadow-md">Local AI video — from a single clip to a full storyboarded film</p>
          </div>
        </div>

        {/* First-run getting started (dismissible) */}
        {showGettingStarted && (
          <div className="mx-8 mt-6 rounded-xl border border-zinc-800 bg-zinc-900/70 p-4" role="region" aria-label="Getting started">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <h3 className="text-sm font-semibold text-white mb-2">Getting started</h3>
                <ol className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-zinc-400">
                  <li className="rounded-lg bg-zinc-950/50 p-3">
                    <span className="text-zinc-200 font-medium">1. Check your GPU and models</span>
                    <p className="mt-1 leading-relaxed">
                      Settings → AI Models detects your GPU, says which models fit its VRAM, and downloads only what is
                      missing. Quality profiles are recommended per GPU.
                    </p>
                  </li>
                  <li className="rounded-lg bg-zinc-950/50 p-3">
                    <span className="text-zinc-200 font-medium">2. Make a quick video</span>
                    <p className="mt-1 leading-relaxed">
                      Describe an idea, generate one clip, then promote it to a film with <em>Edit in Film Maker</em> — the
                      clip becomes Scene 1 / Shot 1 with its prompt, seed and settings kept.
                    </p>
                  </li>
                  <li className="rounded-lg bg-zinc-950/50 p-3">
                    <span className="text-zinc-200 font-medium">3. Optional: connect an AI Director</span>
                    <p className="mt-1 leading-relaxed">
                      An OpenRouter, Claude, Grok or Gemini key in Settings → API Keys unlocks Build Film with AI, the
                      director bar and prompt refinement — or point it at a local server to keep that offline too.
                      Everything else runs offline already.
                    </p>
                  </li>
                </ol>
              </div>
              <button
                onClick={dismissGettingStarted}
                className="text-xs text-zinc-500 hover:text-white px-2 py-1 rounded hover:bg-zinc-800"
                aria-label="Dismiss getting started"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* The front door: four verbs, then the studio for people who want the whole pipeline. */}
        <section className="px-8 pt-8" aria-labelledby="make-heading">
          <h2 id="make-heading" className="text-xl font-semibold text-white mb-1">What do you want to make?</h2>
          <p className="text-sm text-zinc-500 mb-4">Everything below runs on this computer. Pick a verb; you can promote any result to a film later.</p>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4" data-testid="front-door">
            <button
              onClick={openQuickMode}
              className="group text-left rounded-xl border border-zinc-800 bg-zinc-900 hover:border-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400 p-5 transition-colors"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="p-2 rounded-lg bg-violet-600/20 text-violet-300"><Zap className="h-5 w-5" /></span>
                <span className="text-base font-semibold text-white">Create</span>
              </div>
              <p className="text-sm text-zinc-400 leading-relaxed">
                Describe a clip or a still, pick Fast or Balanced, and generate in a minute or three. LoRAs you trained are one checkbox away.
              </p>
              <span className="inline-block mt-3 text-xs text-violet-300 group-hover:text-violet-200">Make a quick video →</span>
            </button>
            <div className="group rounded-xl border border-zinc-800 bg-zinc-900 hover:border-teal-500 p-5 transition-colors flex flex-col">
              <div className="flex items-center gap-2 mb-2">
                <span className="p-2 rounded-lg bg-teal-600/20 text-teal-300"><ImageIcon className="h-5 w-5" /></span>
                <span className="text-base font-semibold text-white">Reproduce</span>
              </div>
              <p className="text-sm text-zinc-400 leading-relaxed">
                Give it an image or a video. The local vision stack reads it, builds an editable ShotSpec, renders candidates, scores them against the original and keeps going until they match.
              </p>
              <div className="mt-3 flex gap-3">
                <button onClick={() => setCurrentView('analyze-image')} className="text-xs text-teal-300 hover:text-teal-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-400 rounded">Reproduce image →</button>
                <button onClick={openAnalyzeVideo} className="text-xs text-teal-300 hover:text-teal-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-400 rounded">Reproduce video →</button>
              </div>
            </div>
            <button
              onClick={openTrain}
              className="group text-left rounded-xl border border-zinc-800 bg-zinc-900 hover:border-fuchsia-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-fuchsia-400 p-5 transition-colors"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="p-2 rounded-lg bg-fuchsia-600/20 text-fuchsia-300"><Layers className="h-5 w-5" /></span>
                <span className="text-base font-semibold text-white">Train</span>
              </div>
              <p className="text-sm text-zinc-400 leading-relaxed">
                Teach the image model a character, style or object: a folder, a video or your own History becomes a captioned dataset and a LoRA that fits a 12 GB card.
              </p>
              <span className="inline-block mt-3 text-xs text-fuchsia-300 group-hover:text-fuchsia-200">Train a LoRA →</span>
            </button>
            <button
              onClick={openHistory}
              className="group text-left rounded-xl border border-zinc-800 bg-zinc-900 hover:border-amber-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 p-5 transition-colors"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="p-2 rounded-lg bg-amber-600/20 text-amber-300"><History className="h-5 w-5" /></span>
                <span className="text-base font-semibold text-white">History</span>
              </div>
              <p className="text-sm text-zinc-400 leading-relaxed">
                Every image, video, analysis, download and training run, live as it happens, with its prompt, seed, settings and lineage. Re-run, cancel or pick up where you left off.
              </p>
              <span className="inline-block mt-3 text-xs text-amber-300 group-hover:text-amber-200">Open History →</span>
            </button>
          </div>
          <button
            onClick={() => startCreate('storyboard')}
            className="group mt-4 w-full text-left rounded-xl border border-zinc-800 bg-zinc-900/60 hover:border-blue-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 p-4 transition-colors flex items-center gap-4"
            aria-label="Film Studio (advanced): create a film project"
          >
            <span className="p-2 rounded-lg bg-blue-600/20 text-blue-300"><Clapperboard className="h-5 w-5" /></span>
            <span className="flex-1">
              <span className="text-sm font-semibold text-white">Film Studio <span className="ml-1 text-[10px] font-normal uppercase tracking-wide text-zinc-500">advanced</span></span>
              <span className="block text-xs text-zinc-400 mt-0.5">Script, characters and locations, a storyboard with a 3D shot composer, continuity checks, an AI Director, a production queue and a timeline for the final cut.</span>
            </span>
            <span className="text-xs text-blue-300 group-hover:text-blue-200 whitespace-nowrap">New film →</span>
          </button>
        </section>

        {/* Projects Grid */}
        <div className="p-8">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-semibold text-white">Projects</h2>
          </div>

          {projects.length === 0 ? (
            <div className="text-center py-16">
              <Folder className="h-16 w-16 text-zinc-700 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-zinc-400 mb-2">No projects yet</h3>
              <p className="text-zinc-500 mb-6">Create your first project to get started</p>
              <Button
                onClick={() => startCreate('gen-space')}
                className="bg-blue-600 hover:bg-blue-500"
              >
                <Plus className="h-4 w-4 mr-2" />
                Create Project
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {projects.map(project => (
                <ProjectCard
                  key={project.id}
                  project={project}
                  onOpen={() => openProject(project.id)}
                  onDelete={() => {
                    if (confirm(`Delete "${project.name}"?`)) {
                      deleteProject(project.id)
                    }
                  }}
                  onRename={() => handleRenameProject(project.id, project.name)}
                />
              ))}
            </div>
          )}
        </div>
      </main>
      
      {/* Create Project Modal */}
      {isCreating && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl p-6 w-full max-w-md border border-zinc-800">
            <h2 className="text-xl font-semibold text-white mb-1">
              {createTarget === 'storyboard' ? 'Create New Film' : 'Create New Project'}
            </h2>
            <p className="text-xs text-zinc-500 mb-4">
              {createTarget === 'storyboard'
                ? 'Opens in the Storyboard tab — every project also has a Gen Space and a Video Editor.'
                : 'Opens in Gen Space — switch to Storyboard any time to make it a film.'}
            </p>
            <input
              type="text"
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              placeholder="Project name"
              className="w-full px-4 py-3 rounded-lg bg-zinc-800 border border-zinc-700 text-white placeholder:text-zinc-500 focus:outline-none focus:border-blue-500"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && handleCreateProject()}
            />
            <div className="flex gap-3 mt-6">
              <Button
                variant="outline"
                onClick={() => { setIsCreating(false); setNewProjectName('') }}
                className="flex-1 border-zinc-700"
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateProject}
                disabled={!newProjectName.trim()}
                className="flex-1 bg-blue-600 hover:bg-blue-500"
              >
                Create
              </Button>
            </div>
          </div>
        </div>
      )}
      
      {/* Rename Modal */}
      {renamingId && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl p-6 w-full max-w-md border border-zinc-800">
            <h2 className="text-xl font-semibold text-white mb-4">Rename Project</h2>
            <input
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder="Project name"
              className="w-full px-4 py-3 rounded-lg bg-zinc-800 border border-zinc-700 text-white placeholder:text-zinc-500 focus:outline-none focus:border-blue-500"
              autoFocus
              onKeyDown={(e) => e.key === 'Enter' && submitRename()}
            />
            <div className="flex gap-3 mt-6">
              <Button
                variant="outline"
                onClick={() => { setRenamingId(null); setRenameValue('') }}
                className="flex-1 border-zinc-700"
              >
                Cancel
              </Button>
              <Button
                onClick={submitRename}
                disabled={!renameValue.trim()}
                className="flex-1 bg-blue-600 hover:bg-blue-500"
              >
                Save
              </Button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
