import * as Slider from '@radix-ui/react-slider';
import { useAppStore } from '../store';

const MIN_YEAR = -3400;
const MAX_YEAR = 2000;
const STEP = 50;

function formatYear(year: number): string {
  if (year < 0) {
    return `${Math.abs(year)} BCE`;
  } else if (year === 0) {
    return '1 CE';
  } else {
    return `${year} CE`;
  }
}

export function TimelineSlider() {
  const { selectedYear, setSelectedYear } = useAppStore();

  return (
    <div className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center gap-6">
          <span className="text-sm text-gray-500 w-24">{formatYear(MIN_YEAR)}</span>

          <Slider.Root
            className="relative flex items-center select-none touch-none w-full h-5"
            value={[selectedYear]}
            onValueChange={([value]) => setSelectedYear(value)}
            min={MIN_YEAR}
            max={MAX_YEAR}
            step={STEP}
          >
            <Slider.Track className="bg-gray-200 relative grow rounded-full h-2">
              <Slider.Range className="absolute bg-blue-500 rounded-full h-full" />
            </Slider.Track>
            <Slider.Thumb
              className="block w-5 h-5 bg-white border-2 border-blue-500 rounded-full shadow-md focus:outline-none focus:ring-2 focus:ring-blue-400 cursor-grab active:cursor-grabbing"
              aria-label="Year"
            />
          </Slider.Root>

          <span className="text-sm text-gray-500 w-24 text-right">{formatYear(MAX_YEAR)}</span>

          <div className="bg-blue-50 text-blue-700 px-4 py-2 rounded-lg font-medium min-w-32 text-center">
            {formatYear(selectedYear)}
          </div>
        </div>
      </div>
    </div>
  );
}
