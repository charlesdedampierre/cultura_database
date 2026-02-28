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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen flex flex-col bg-white">
        {/* Timeline Slider */}
        <TimelineSlider />

        {/* Map - fixed height */}
        <div className="h-[55vh] relative overflow-hidden flex-shrink-0">
          <WorldMap />
        </div>

        {/* Polity Panel - below map, two columns */}
        <div className="flex-1 border-t border-gray-200 bg-white">
          <PolityPanel />
        </div>
      </div>
    </QueryClientProvider>
  );
}

export default App;
