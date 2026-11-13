// Leaflet.draw expects a global L; import this module before "leaflet-draw".
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw/dist/leaflet.draw.css";

(window as unknown as { L: typeof L }).L = L;

export default L;
