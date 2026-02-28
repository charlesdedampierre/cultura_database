import { useState, useCallback } from 'react';
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

function parseYearInput(input: string): number | null {
  const trimmed = input.trim().toUpperCase();
  // Try "XXXX BCE" format
  const bceMatch = trimmed.match(/^(\d+)\s*BCE$/);
  if (bceMatch) {
    return -parseInt(bceMatch[1], 10);
  }
  // Try "XXXX CE" format
  const ceMatch = trimmed.match(/^(\d+)\s*CE$/);
  if (ceMatch) {
    return parseInt(ceMatch[1], 10);
  }
  // Try plain number (negative = BCE, positive = CE)
  const num = parseInt(trimmed, 10);
  if (!isNaN(num)) {
    return num;
  }
  return null;
}

export function TimelineSlider() {
  const { selectedYear, setSelectedYear } = useAppStore();
  const [yearInput, setYearInput] = useState('');
  const [inputError, setInputError] = useState(false);

  const handleYearSubmit = useCallback(() => {
    const parsed = parseYearInput(yearInput);
    if (parsed !== null && parsed >= MIN_YEAR && parsed <= MAX_YEAR) {
      setSelectedYear(parsed);
      setYearInput('');
      setInputError(false);
    } else {
      setInputError(true);
    }
  }, [yearInput, setSelectedYear]);

  return (
    <div className="bg-white border-b border-gray-200 px-6 py-4">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500 whitespace-nowrap">{formatYear(MIN_YEAR)}</span>

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

          <span className="text-sm text-gray-500 whitespace-nowrap">{formatYear(MAX_YEAR)}</span>

          <div className="bg-blue-50 text-blue-700 px-4 py-2 rounded-lg font-medium min-w-32 text-center whitespace-nowrap">
            {formatYear(selectedYear)}
          </div>

          {/* Year input */}
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={yearInput}
              onChange={(e) => {
                setYearInput(e.target.value);
                setInputError(false);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleYearSubmit();
              }}
              placeholder="e.g. 500 BCE"
              className={`w-28 text-sm px-2 py-1.5 rounded border ${
                inputError ? 'border-red-400 bg-red-50' : 'border-gray-300'
              } focus:outline-none focus:ring-1 focus:ring-blue-400`}
            />
            <button
              onClick={handleYearSubmit}
              className="text-sm px-2 py-1.5 bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors whitespace-nowrap"
            >
              Go
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
