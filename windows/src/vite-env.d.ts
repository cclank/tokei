/// <reference types="vite/client" />

declare module "*.strings?raw" {
  const content: string;
  export default content;
}
