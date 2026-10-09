// 数据面板专用的动画与滚动条样式（不改全局 styles.css），由 DashboardPage 挂一次。
// dash-badge-*：新解锁的成就徽章轻弹入（spring response 0.45 / damping 0.5）+ 金光扫过（BadgeView）；
// dash-confetti-fall：跨 token 里程碑时彩屑从顶部落下并淡出（ConfettiView）。
const CSS = `
.dash-hscroll {
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, 0.14) transparent;
}
.dash-hscroll::-webkit-scrollbar { height: 6px; }
.dash-hscroll::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.14); border-radius: 3px; }
.dash-hscroll::-webkit-scrollbar-track { background: transparent; }

.dash-cell { transition: box-shadow 0.2s ease-out; }

.dash-bar { transition: width 0.22s ease-in-out, height 0.22s ease-in-out; }

@keyframes dash-badge-pop {
  0% { transform: scale(0.7); }
  45% { transform: scale(1.08); }
  70% { transform: scale(0.97); }
  85% { transform: scale(1.015); }
  100% { transform: scale(1); }
}
@keyframes dash-badge-shimmer {
  from { left: -130%; }
  to { left: 130%; }
}

@keyframes dash-confetti-fall {
  from { transform: translateY(-40px) rotate(var(--dash-rot)); opacity: 1; }
  to { transform: translateY(260px) rotate(var(--dash-rot)); opacity: 0; }
}

@keyframes dash-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
`;

export function DashboardStyles() {
  return <style>{CSS}</style>;
}
