import * as d3 from 'd3';
import type { WeatherData } from '../../services/api';

interface WeatherPoint {
  month: string;
  precip: number;
  temp: number;
}

function shortMonthLabel(value: string) {
  const [year, month] = value.split('-');
  if (!year || !month) {
    return value;
  }
  return `${year.slice(2)}-${month}`;
}

export function renderWeatherChart(container: HTMLDivElement, data: WeatherData) {
  container.replaceChildren();
  container.style.position = 'relative';

  const width = Math.max(320, container.clientWidth);
  const height = Math.max(220, container.clientHeight);
  const margin = { top: 44, right: 56, bottom: 56, left: 56 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  if (innerWidth <= 0 || innerHeight <= 0) {
    return;
  }

  const points: WeatherPoint[] = data.months.map((month, idx) => ({
    month,
    precip: Number.isFinite(data.PRECTOTCORR[idx]) ? data.PRECTOTCORR[idx] : 0,
    temp: Number.isFinite(data.T2M[idx]) ? data.T2M[idx] : 0,
  }));

  const x = d3
    .scaleBand<string>()
    .domain(points.map((point) => point.month))
    .range([margin.left, width - margin.right])
    .padding(0.18);

  const maxPrecip = d3.max(points, (point) => point.precip) ?? 0;
  const minTemp = d3.min(points, (point) => point.temp) ?? 0;
  const maxTemp = d3.max(points, (point) => point.temp) ?? 0;

  const yLeft = d3
    .scaleLinear()
    .domain([0, Math.max(10, maxPrecip * 1.15)])
    .nice()
    .range([height - margin.bottom, margin.top]);

  const yRight = d3
    .scaleLinear()
    .domain([Math.min(0, minTemp - 2), maxTemp + 2])
    .nice()
    .range([height - margin.bottom, margin.top]);

  const svg = d3
    .select(container)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img')
    .attr('aria-label', 'Weather chart for precipitation and temperature');

  const tooltip = d3
    .select(container)
    .append('div')
    .attr('class', 'chart-tooltip')
    .style('opacity', '0');

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(
      d3
        .axisLeft(yLeft)
        .ticks(5)
        .tickSize(-innerWidth)
        .tickFormat(() => ''),
    )
    .call((axis) => axis.select('.domain').remove())
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.24)'));

  const bars = svg
    .append('g')
    .selectAll('rect')
    .data(points)
    .join('rect')
    .attr('x', (point) => x(point.month) ?? 0)
    .attr('y', (point) => yLeft(point.precip))
    .attr('width', x.bandwidth())
    .attr('height', (point) => Math.max(0, height - margin.bottom - yLeft(point.precip)))
    .attr('fill', 'rgba(34,211,238,0.55)')
    .attr('opacity', 0.8);

  const line = d3
    .line<WeatherPoint>()
    .defined((point) => Number.isFinite(point.temp))
    .x((point) => (x(point.month) ?? 0) + x.bandwidth() / 2)
    .y((point) => yRight(point.temp));

  svg
    .append('path')
    .datum(points)
    .attr('fill', 'none')
    .attr('stroke', '#e879f9')
    .attr('stroke-width', 2.5)
    .attr('d', line);

  const tempDots = svg
    .append('g')
    .selectAll('circle')
    .data(points)
    .join('circle')
    .attr('cx', (point) => (x(point.month) ?? 0) + x.bandwidth() / 2)
    .attr('cy', (point) => yRight(point.temp))
    .attr('r', 2.7)
    .attr('fill', '#f0abfc')
    .attr('stroke', '#e879f9')
    .attr('stroke-width', 1.2);

  const tickStep = Math.max(1, Math.ceil(points.length / 8));
  const xTickValues = points
    .map((point) => point.month)
    .filter((_month, idx, arr) => idx % tickStep === 0 || idx === arr.length - 1);

  svg
    .append('g')
    .attr('transform', `translate(0,${height - margin.bottom})`)
    .call(
      d3
        .axisBottom(x)
        .tickValues(xTickValues)
        .tickFormat((value) => shortMonthLabel(String(value))),
    )
    .call((axis) => axis.select('.domain').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) =>
      axis
        .selectAll<SVGTextElement, string>('.tick text')
        .attr('fill', '#cbd5e1')
        .attr('font-size', 11)
        .attr('transform', 'rotate(-42)')
        .style('text-anchor', 'end'),
    );

  svg
    .append('g')
    .attr('transform', `translate(${margin.left},0)`)
    .call(d3.axisLeft(yLeft).ticks(5))
    .call((axis) => axis.select('.domain').attr('stroke', 'rgba(148,163,184,0.45)'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#cbd5e1').attr('font-size', 11));

  svg
    .append('g')
    .attr('transform', `translate(${width - margin.right},0)`)
    .call(d3.axisRight(yRight).ticks(5))
    .call((axis) => axis.select('.domain').attr('stroke', 'rgba(148,163,184,0.45)'))
    .call((axis) => axis.selectAll('.tick line').attr('stroke', 'rgba(148,163,184,0.35)'))
    .call((axis) => axis.selectAll('.tick text').attr('fill', '#cbd5e1').attr('font-size', 11));

  svg
    .append('text')
    .attr('x', margin.left)
    .attr('y', 16)
    .attr('fill', '#67e8f9')
    .attr('font-size', 12)
    .text('Precipitation (mm)');

  svg
    .append('text')
    .attr('x', width - margin.right)
    .attr('y', 16)
    .attr('text-anchor', 'end')
    .attr('fill', '#f0abfc')
    .attr('font-size', 12)
    .text('Temp Mean (degC)');

  const legend = svg.append('g').attr('transform', `translate(${width / 2 - 110}, 8)`);
  legend.append('rect').attr('x', 0).attr('y', 2).attr('width', 18).attr('height', 10).attr('fill', 'rgba(34,211,238,0.8)');
  legend
    .append('text')
    .attr('x', 24)
    .attr('y', 11)
    .attr('font-size', 11)
    .attr('fill', '#e2e8f0')
    .text('Precipitation');
  legend
    .append('line')
    .attr('x1', 120)
    .attr('x2', 140)
    .attr('y1', 7)
    .attr('y2', 7)
    .attr('stroke', '#e879f9')
    .attr('stroke-width', 2.5);
  legend
    .append('text')
    .attr('x', 146)
    .attr('y', 11)
    .attr('font-size', 11)
    .attr('fill', '#e2e8f0')
    .text('Temp Mean');

  const hoverLine = svg
    .append('line')
    .attr('stroke', 'rgba(103,232,249,0.6)')
    .attr('stroke-width', 1.1)
    .attr('y1', margin.top)
    .attr('y2', height - margin.bottom)
    .style('display', 'none');

  const hoverPrecip = svg
    .append('circle')
    .attr('r', 4.2)
    .attr('fill', '#67e8f9')
    .attr('stroke', '#22d3ee')
    .attr('stroke-width', 1.3)
    .style('display', 'none');

  const hoverTemp = svg
    .append('circle')
    .attr('r', 4.2)
    .attr('fill', '#f0abfc')
    .attr('stroke', '#e879f9')
    .attr('stroke-width', 1.3)
    .style('display', 'none');

  svg
    .append('g')
    .selectAll('rect')
    .data(points)
    .join('rect')
    .attr('x', (point) => x(point.month) ?? 0)
    .attr('y', margin.top)
    .attr('width', x.bandwidth())
    .attr('height', innerHeight)
    .attr('fill', 'transparent')
    .style('cursor', 'crosshair')
    .on('mouseenter', () => {
      hoverLine.style('display', 'block');
      hoverPrecip.style('display', 'block');
      hoverTemp.style('display', 'block');
      tooltip.style('opacity', '1');
    })
    .on('mousemove', (event, point) => {
      const xPos = (x(point.month) ?? 0) + x.bandwidth() / 2;
      const yTemp = yRight(point.temp);
      const yPrecip = yLeft(point.precip);

      hoverLine.attr('x1', xPos).attr('x2', xPos);
      hoverPrecip.attr('cx', xPos).attr('cy', yPrecip);
      hoverTemp.attr('cx', xPos).attr('cy', yTemp);

      bars.attr('opacity', (item) => (item.month === point.month ? 1 : 0.45));
      tempDots
        .attr('r', (item) => (item.month === point.month ? 4.1 : 2.7))
        .attr('fill', (item) => (item.month === point.month ? '#fdf4ff' : '#f0abfc'));

      const [pointerX, pointerY] = d3.pointer(event, container);
      const tooltipLeft = Math.max(8, Math.min(width - 190, pointerX + 14));
      const tooltipTop = Math.max(8, Math.min(height - 80, pointerY - 16));

      tooltip
        .style('left', `${tooltipLeft}px`)
        .style('top', `${tooltipTop}px`)
        .html(
          `<div class="chart-tooltip-title">${point.month}</div>
           <div><span class="swatch-cyan"></span>Precipitation: ${point.precip.toFixed(1)} mm</div>
           <div><span class="swatch-pink"></span>Temp Mean: ${point.temp.toFixed(1)} °C</div>`,
        );
    })
    .on('mouseleave', () => {
      hoverLine.style('display', 'none');
      hoverPrecip.style('display', 'none');
      hoverTemp.style('display', 'none');
      tooltip.style('opacity', '0');
      bars.attr('opacity', 0.8);
      tempDots.attr('r', 2.7).attr('fill', '#f0abfc');
    });
}
