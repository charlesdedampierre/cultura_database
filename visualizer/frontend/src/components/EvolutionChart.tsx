import { useQuery } from '@tanstack/react-query';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Label,
} from 'recharts';
import { useAppStore } from '../store';

interface EvolutionPoint {
  year: number;
  count: number;
}

type EvolutionData = Record<string, EvolutionPoint[]>;

function formatYear(year: number): string {
  if (year < 0) {
    return `${Math.abs(year)} BCE`;
  }
  return `${year} CE`;
}

async function loadEvolutionData(): Promise<EvolutionData> {
  const response = await fetch('/evolution.json');
  return response.json();
}

export function EvolutionChart() {
  const { selectedPolityId, filterYear, setFilterYear } = useAppStore();

  const { data: allEvolution } = useQuery({
    queryKey: ['evolutionData'],
    queryFn: loadEvolutionData,
    staleTime: Infinity,
  });

  if (!selectedPolityId || !allEvolution) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        {selectedPolityId ? 'Loading...' : 'Select a polity to view evolution'}
      </div>
    );
  }

  const evolution = allEvolution[String(selectedPolityId)] || [];

  if (evolution.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        No evolution data available
      </div>
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleChartClick = (data: any) => {
    if (data?.activePayload?.[0]) {
      setFilterYear(data.activePayload[0].payload.year);
    }
  };

  return (
    <div className="h-full relative">
      {filterYear != null && (
        <div className="absolute top-0 right-0 z-10 bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded cursor-pointer"
             onClick={() => setFilterYear(null)}>
          {formatYear(filterYear)} ✕
        </div>
      )}
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={evolution}
          margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
          onClick={handleChartClick}
          style={{ cursor: 'pointer' }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="year"
            tickFormatter={(year) => formatYear(year)}
            tick={{ fontSize: 11 }}
            stroke="#9ca3af"
          />
          <YAxis
            tickFormatter={(value) => value.toLocaleString()}
            tick={{ fontSize: 11 }}
            stroke="#9ca3af"
          >
            <Label
              value="Number of Individuals"
              angle={-90}
              position="insideLeft"
              style={{ textAnchor: 'middle', fill: '#6b7280', fontSize: 11 }}
              offset={0}
            />
          </YAxis>
          <Tooltip
            labelFormatter={(year) => formatYear(year as number)}
            formatter={(value) => [(value as number).toLocaleString(), 'Individuals']}
            contentStyle={{
              backgroundColor: 'white',
              border: '1px solid #e5e7eb',
              borderRadius: '8px',
              fontSize: '12px',
            }}
          />
          {filterYear != null && (
            <ReferenceLine x={filterYear} stroke="#3b82f6" strokeWidth={2} strokeDasharray="4 4" />
          )}
          <Line
            type="monotone"
            dataKey="count"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={(props) => {
              const { cx, cy, payload, index } = props;
              if (cx == null || cy == null) return <circle key={`dot-${index}`} r={0} />;
              const isSelected = filterYear === payload.year;
              return (
                <circle
                  key={`dot-${index}`}
                  cx={cx}
                  cy={cy}
                  r={isSelected ? 6 : 4}
                  fill={isSelected ? '#1d4ed8' : '#3b82f6'}
                  stroke={isSelected ? '#1e40af' : 'none'}
                  strokeWidth={isSelected ? 2 : 0}
                />
              );
            }}
            activeDot={{ r: 6, fill: '#2563eb' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
