import { useQuery } from '@tanstack/react-query';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Label,
} from 'recharts';
import { useAppStore } from '../store';

interface OccupationEntry {
  name: string;
  count: number;
}

type OccupationsData = Record<string, OccupationEntry[]>;

async function loadOccupationsData(): Promise<OccupationsData> {
  const response = await fetch('/occupations.json');
  return response.json();
}

export function OccupationsChart() {
  const { selectedPolityId, filterOccupation, setFilterOccupation } = useAppStore();

  const { data: allOccupations } = useQuery({
    queryKey: ['occupationsData'],
    queryFn: loadOccupationsData,
    staleTime: Infinity,
  });

  if (!selectedPolityId || !allOccupations) {
    return null;
  }

  const occupations = allOccupations[String(selectedPolityId)] || [];

  if (occupations.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        No occupation data available
      </div>
    );
  }

  // Dynamic height: at least 28px per occupation, minimum 200px
  const chartHeight = Math.max(200, occupations.length * 28);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleBarClick = (data: any) => {
    const name = data?.name ?? data?.payload?.name;
    if (name) {
      setFilterOccupation(name);
    }
  };

  return (
    <div className="h-full relative overflow-y-auto">
      {filterOccupation != null && (
        <div className="absolute top-0 right-0 z-10 bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded cursor-pointer"
             onClick={() => setFilterOccupation(null)}>
          {filterOccupation} ✕
        </div>
      )}
      <div style={{ height: chartHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={occupations}
            layout="vertical"
            margin={{ top: 5, right: 20, left: 5, bottom: 5 }}
            style={{ cursor: 'pointer' }}
            onClick={(state) => {
              if (state?.activePayload?.[0]?.payload) {
                handleBarClick(state.activePayload[0].payload);
              }
            }}
          >
            <XAxis
              type="number"
              tickFormatter={(value) => value.toLocaleString()}
              tick={{ fontSize: 11 }}
              stroke="#9ca3af"
            >
              <Label
                value="Number of Individuals"
                position="insideBottom"
                offset={-2}
                style={{ textAnchor: 'middle', fill: '#6b7280', fontSize: 11 }}
              />
            </XAxis>
            <YAxis
              type="category"
              dataKey="name"
              width={120}
              tick={{ fontSize: 11 }}
              stroke="#9ca3af"
              interval={0}
            />
            <Tooltip
              formatter={(value) => [(value as number).toLocaleString(), 'Individuals']}
              contentStyle={{
                backgroundColor: 'white',
                border: '1px solid #e5e7eb',
                borderRadius: '8px',
                fontSize: '12px',
              }}
            />
            <Bar
              dataKey="count"
              radius={[0, 4, 4, 0]}
            >
              {occupations.map((entry) => {
                const isSelected = filterOccupation === entry.name;
                const isDimmed = filterOccupation != null && !isSelected;
                return (
                  <Cell
                    key={entry.name}
                    fill={isSelected ? '#059669' : '#10b981'}
                    opacity={isDimmed ? 0.4 : 1}
                    cursor="pointer"
                  />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
