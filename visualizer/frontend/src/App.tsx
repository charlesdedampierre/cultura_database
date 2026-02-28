import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TimelineSlider } from './components/TimelineSlider';
import { WorldMap } from './components/WorldMap';
import { PolityPanel } from './components/PolityPanel';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 3,
      refetchOnWindowFocus: false,
    },
  },
});

function LogoIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="20" cy="20" r="18" fill="#3b82f6" />
      <circle cx="20" cy="20" r="14" fill="none" stroke="white" strokeWidth="1.5" />
      <path d="M6 20h28M20 6c-4 4-6 9-6 14s2 10 6 14c4-4 6-9 6-14s-2-10-6-14z" stroke="white" strokeWidth="1.5" fill="none" />
      <path d="M8 12h24M8 28h24" stroke="white" strokeWidth="1" opacity="0.6" />
      <circle cx="20" cy="20" r="2" fill="white" />
    </svg>
  );
}

function AboutModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <LogoIcon className="w-8 h-8" />
            <h2 className="text-xl font-bold text-gray-900">About</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="space-y-3 text-sm text-gray-600 leading-relaxed">
          <p>
            The <strong>Historical Polity Visualizer</strong> is an interactive tool for exploring
            the rise and fall of political entities throughout human history, from ancient
            civilizations to modern states.
          </p>
          <p>
            Navigate through time using the timeline slider to see which polities were active
            at any given period. Click on a polity on the map to explore its notable individuals,
            occupational breakdown, and population evolution over centuries.
          </p>
          <p>
            Data is sourced from <a href="https://www.wikidata.org" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">Wikidata</a>,
            covering hundreds of thousands of historical figures and thousands of political
            entities spanning over 5,000 years of recorded history.
          </p>
          <p>
            Use the charts to filter individuals by occupation or time period. Toggle between
            a flat map and a 3D globe view for different perspectives on historical geography.
          </p>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [showAbout, setShowAbout] = useState(false);

  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen flex flex-col bg-white">
        {/* Header */}
        <header className="bg-gray-900 text-white px-6 py-3 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            <LogoIcon className="w-8 h-8" />
            <h1 className="text-lg font-semibold tracking-tight">Historical Polity Visualizer</h1>
          </div>
          <nav className="flex items-center gap-4">
            <button
              onClick={() => setShowAbout(true)}
              className="text-sm text-gray-300 hover:text-white transition-colors"
            >
              About
            </button>
          </nav>
        </header>

        {/* Map - fixed height */}
        <div className="h-[55vh] relative overflow-hidden flex-shrink-0">
          <WorldMap />
        </div>

        {/* Timeline Slider */}
        <TimelineSlider />

        {/* Polity Panel - below map, two columns */}
        <div className="flex-1 border-t border-gray-200 bg-white">
          <PolityPanel />
        </div>

        {/* Footer */}
        <footer className="bg-gray-900 text-gray-400 px-6 py-4 flex-shrink-0">
          <div className="max-w-7xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <LogoIcon className="w-6 h-6" />
              <span className="text-sm">Historical Polity Visualizer</span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <button
                onClick={() => setShowAbout(true)}
                className="hover:text-white transition-colors"
              >
                About
              </button>
              <span className="text-gray-600">|</span>
              <span>Data from <a href="https://www.wikidata.org" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">Wikidata</a></span>
            </div>
          </div>
        </footer>

        {/* About modal */}
        {showAbout && <AboutModal onClose={() => setShowAbout(false)} />}
      </div>
    </QueryClientProvider>
  );
}

export default App;
