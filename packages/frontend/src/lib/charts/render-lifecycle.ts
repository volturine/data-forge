export type ChartRenderer = (element: HTMLDivElement, width: number, height: number) => void;

export function observeChart(element: HTMLDivElement, renderer: ChartRenderer): () => void {
	let animationFrame = 0;
	const draw = () => {
		element.querySelectorAll('svg').forEach((svg) => svg.remove());
		const bounds = element.getBoundingClientRect();
		renderer(element, bounds.width || 400, bounds.height || 300);
	};
	const observer = new ResizeObserver(() => {
		cancelAnimationFrame(animationFrame);
		animationFrame = requestAnimationFrame(draw);
	});
	observer.observe(element);
	draw();
	return () => {
		observer.disconnect();
		cancelAnimationFrame(animationFrame);
		element.querySelectorAll('svg').forEach((svg) => svg.remove());
	};
}
