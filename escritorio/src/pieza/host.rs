// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri» (Mac, Windows y Linux, en Rust con Tauri): la app nativa genérica. Una ventana con la interfaz de ui/
//! servida por el protocolo propio, el puente con la interfaz (host.enviar ↔ window.<App>.*) y los scripts de bin/ con el
//! Python portátil. Reemplaza a «host-mac» (Swift) y a «host-escritorio» (Electron) con la misma API: un solo host para los
//! tres sistemas. Nada de una app adentro: todo sale de app.json y de las `Opciones`.
//!
//!   fn main() {
//!       pieza::host::arrancar(tauri::generate_context!(), pieza::host::Opciones::default(), |host| {
//!           host.registrar("exportar", |datos, host, ctx| { … host.llamar("exportado", json!({"ok": true}), ctx.destino()); });
//!       });
//!   }
//!
//! Seguridad (igual o mejor que la mejor app de la familia):
//!   · la ventana solo navega dentro de ui/ (https → navegador, por el `abrirEnlace` que registró la app si hay uno) y nunca
//!     abre otras ventanas;
//!   · el puente solo atiende las ventanas propias (la principal y las que la app agrega) con la página en ui/, y responde a la
//!     que pidió;
//!   · las acciones declaradas (acciones.json) validan los datos por sus reglas, lo de la persona va por archivo de entrada y
//!     todo tiene límite de tiempo; los scripts no heredan variables <ID>_*;
//!   · el protocolo sirve solo archivos de ui/ y, si la app lo pide, los que su resolvedor de medios aprueba.

use super::enchufe::{self as e, Accion, App, Config, Idioma, Limite};
use super::procesador::{self as p, Fila, LectorProgreso, Opciones as OpcionesScript, Procesador};
use super::protocolo;
use super::sistema::{self, Notificaciones, Secretos};
use super::vigilante::Vigilante;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex, OnceLock, RwLock};
use std::thread;
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, Submenu, SubmenuBuilder};
use tauri::webview::{NewWindowResponse, PageLoadEvent};
use tauri::{AppHandle, Manager, RunEvent, Theme, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent, Wry};

pub const PRINCIPAL: &str = "principal";
const TEXTO_DATOS: &str = "No entendí lo que pediste. Intenta de nuevo.";
const TEXTO_FALTA: &str = "Falta algo para hacer esto.";

// ───────────── Opciones ─────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AlCerrar {
    /// Cerrar la ventana cierra la app.
    Salir,
    /// Sigue viva en la bandeja (o en la barra de menú del Mac) hasta «Salir».
    Esconder,
}

#[derive(Clone)]
pub struct Ventana {
    pub ancho: f64,
    pub alto: f64,
    pub min_ancho: f64,
    pub min_alto: f64,
    /// Color de fondo mientras carga (#rrggbb).
    pub fondo_claro: String,
    pub fondo_oscuro: String,
    pub al_cerrar: AlCerrar,
    /// `false`: sin marco (la interfaz dibuja su barra y usa `data-tauri-drag-region`).
    pub marco: bool,
    /// Mac: barra de título transparente, la interfaz llega hasta arriba (los botones del Mac quedan encima).
    pub barra_transparente: bool,
    /// Con `barra_transparente`: los px de arriba que mueven la ventana al arrastrar (doble clic: agrandar), como la barra de
    /// título que no se ve. Lo que se toca ahí (botones, campos, enlaces) sigue funcionando. 0: la interfaz lo resuelve.
    pub alto_franja: f64,
    /// Mac: vidrio (vibrancy); Windows 11: Mica.
    pub vidrio: bool,
    /// Con qué nombre se recuerda el tamaño y el lugar (ventana.json).
    pub nombre: String,
}
impl Default for Ventana {
    fn default() -> Self {
        Ventana {
            ancho: 1280.0,
            alto: 800.0,
            min_ancho: 720.0,
            min_alto: 520.0,
            fondo_claro: "#f7f7f5".into(),
            fondo_oscuro: "#1c1c1e".into(),
            al_cerrar: AlCerrar::Salir,
            marco: true,
            barra_transparente: false,
            alto_franja: 0.0,
            vidrio: false,
            nombre: "ventana".into(),
        }
    }
}

/// La carpeta que elige la persona (`host.carpeta()`): su ruta real queda en `config.<clave>` (en app.json con
/// "interfaz": false) y trae el inyector `carpetaActual`.
#[derive(Clone)]
pub struct OpcionesCarpeta {
    pub clave: String,
    pub titulo: Option<String>,
    pub boton: Option<String>,
    pub falta: String,
}
impl Default for OpcionesCarpeta {
    fn default() -> Self {
        OpcionesCarpeta { clave: "carpeta".into(), titulo: None, boton: None, falta: "Elige una carpeta primero.".into() }
    }
}

/// Opciones de `guardar_archivo_con`. `titulo` va en español: el host lo traduce.
#[derive(Clone, Debug)]
pub struct ComoGuardar {
    pub privado: Option<bool>,
    /// Bytes; sin decirlo, 50 MB.
    pub maximo: usize,
    /// Dónde abre el diálogo (si existe); sin decirlo, Documentos.
    pub desde: Option<PathBuf>,
    pub titulo: Option<String>,
}
impl Default for ComoGuardar {
    fn default() -> Self {
        ComoGuardar { privado: None, maximo: 50 * 1024 * 1024, desde: None, titulo: None }
    }
}

/// Un ítem de menú. Las etiquetas van en español: el host las traduce con ui/idiomas.
#[derive(Clone)]
pub enum ItemMenu {
    /// Manda `window.<App>.menu({accion})` (nada antes de elegir el idioma). `atajo`: "CmdOrCtrl+N".
    Accion { etiqueta: String, accion: String, atajo: Option<String> },
    /// Corre `f(host)` en el host (abrir una carpeta con el diálogo del sistema…).
    Nativo { etiqueta: String, atajo: Option<String>, f: Arc<dyn Fn(&Host) + Send + Sync> },
    Separador,
}
pub fn item(etiqueta: &str, accion: &str, atajo: Option<&str>) -> ItemMenu {
    ItemMenu::Accion { etiqueta: etiqueta.into(), accion: accion.into(), atajo: atajo.map(String::from) }
}

/// Lo propio del menú: ítems de Archivo (arriba de Salir), de Ver y menús enteros (título, ítems).
#[derive(Clone, Default)]
pub struct MenuPropio {
    /// Deshacer y rehacer los hace la interfaz (`menu({accion: "deshacer"})`): en vez de los del sistema.
    pub deshacer_propio: bool,
    pub archivo: Vec<ItemMenu>,
    pub ver: Vec<ItemMenu>,
    pub extra: Vec<(String, Vec<ItemMenu>)>,
}

/// La pieza «actualizaciones»: el host atiende `buscarActualizacion` y `actualizar` (nunca con algo en curso) y revisa cada
/// 6 h con el idioma elegido.
pub trait Actualizador: Send + Sync {
    /// {hay, version, notas, texto, valores, desarrollo}: lo que va en el estado.
    fn disponible(&self) -> Value;
    /// Revisa ahora: {hay, …, sinConexion}.
    fn revisar(&self, version: &str) -> Value;
    /// Descarga, verifica e instala. avisar({paso, codigo, texto, valores, total, pct?}). Al final la app se cierra.
    fn instalar(&self, host: &Host, avisar: &dyn Fn(Value));
}

pub struct Opciones {
    pub ventana: Ventana,
    /// Enlaces del menú Ayuda (solo https). `ayuda: false`: sin menú Ayuda.
    pub sitio: Option<String>,
    pub codigo: Option<String>,
    pub ayuda: bool,
    /// El objeto `window.<App>` (por defecto el id con mayúscula).
    pub global: Option<String>,
    pub carpeta: Option<OpcionesCarpeta>,
    /// [".md"]: el vigilante de la carpeta (`host.vigilante()`).
    pub vigilar: Option<Vec<String>>,
    /// Otro script de estado (`Some(None)`: ninguno). Por defecto, bin/estado.py si existe.
    pub estado_script: Option<Option<String>>,
    pub limite_estado: u64,
    /// El estado se lee dentro de la fila (nunca a medio guardar).
    pub estado_en_fila: bool,
    /// «Ajustes…» con otro nombre (`Some(None)`: sin él).
    pub titulo_ajustes: Option<Option<String>>,
    pub menu: MenuPropio,
    /// Ícono en la bandeja (Windows, Linux) o en la barra de menú (Mac). Con `AlCerrar::Esconder`, siempre.
    pub bandeja: bool,
    /// Mac: solo en la barra de menú (sin ícono en el Dock).
    pub solo_barra_de_menu: bool,
    /// ¿Mostrar la ventana al arrancar? Sin decirlo, sí, salvo que la app se abrió con `--oculta` (al iniciar sesión).
    pub abrir_al_arrancar: Option<bool>,
    /// Soltar archivos en la ventana: el host guarda las rutas y avisa `soltados {nombres}` (la página no ve rutas).
    pub soltar: bool,
    pub lector_progreso: Option<Arc<dyn LectorProgreso>>,
    pub actualizaciones: Option<Arc<dyn Actualizador>>,
    /// Si la app no guarda `idioma_ui` en config.json.
    pub idioma_elegido: Option<Box<dyn Fn() -> String + Send + Sync>>,
    /// `false` si la interfaz no atiende `menu({accion: "guardar"})`.
    pub guardar_al_salir: bool,
    /// Solo desarrollo y pruebas.
    pub recursos: Option<PathBuf>,
    pub datos: Option<PathBuf>,
    pub python: Option<PathBuf>,
    /// Herramientas de desarrollo de la página (solo en desarrollo).
    pub devtools: bool,
}
impl Default for Opciones {
    fn default() -> Self {
        Opciones {
            ventana: Ventana::default(),
            sitio: None,
            codigo: None,
            ayuda: true,
            global: None,
            carpeta: None,
            vigilar: None,
            estado_script: None,
            limite_estado: 60,
            estado_en_fila: false,
            titulo_ajustes: None,
            menu: MenuPropio::default(),
            bandeja: false,
            solo_barra_de_menu: false,
            abrir_al_arrancar: None,
            soltar: false,
            lector_progreso: None,
            actualizaciones: None,
            idioma_elegido: None,
            guardar_al_salir: true,
            recursos: None,
            datos: None,
            python: None,
            devtools: cfg!(debug_assertions),
        }
    }
}

// ───────────── Lo que recibe una acción propia ─────────────
/// Quién pidió la acción: la ventana principal o una agregada (la respuesta va a ella).
#[derive(Clone, Debug, Default)]
pub struct Ctx {
    pub responder_a: Option<String>,
}
impl Ctx {
    pub fn destino(&self) -> Option<&str> {
        self.responder_a.as_deref()
    }
}

/// Lo que devuelve un inyector cuando falta algo, con su propio texto (en español, con marcadores).
pub struct Falta {
    pub texto: String,
    pub valores: Value,
}
pub enum Inyectado {
    Valor(Value),
    Falta(Falta),
}

type Registrada = Arc<dyn Fn(Value, &Host, Ctx) + Send + Sync>;
type Inyector = Arc<dyn Fn(&Map<String, Value>, &Host) -> Inyectado + Send + Sync>;
type Resolver = Arc<dyn Fn(&str, &Host) -> Option<PathBuf> + Send + Sync>;
type Gancho = Arc<dyn Fn(&Host) + Send + Sync>;
type GanchoEstado = Arc<dyn Fn(Map<String, Value>, &Host) -> Map<String, Value> + Send + Sync>;
type GanchoConfig = Arc<dyn Fn(&Map<String, Value>, &Map<String, Value>, &Host) + Send + Sync>;
type GanchoTocar = Arc<dyn Fn(&str, &Host) + Send + Sync>;
type GanchoSoltar = Arc<dyn Fn(&[PathBuf], &Host) + Send + Sync>;
type GanchoVentana = Arc<dyn Fn(&WebviewWindow, &Host) + Send + Sync>;

#[derive(Default)]
struct Ganchos {
    estado: Option<GanchoEstado>,
    tareas: Option<Gancho>,
    al_cambiar_config: Option<GanchoConfig>,
    antes_de_salir: Option<Gancho>,
    al_tocar_aviso: Option<GanchoTocar>,
    al_soltar: Option<GanchoSoltar>,
    al_crear_ventana: Option<GanchoVentana>,
    despues_del_estado: Option<Gancho>,
}

pub struct Interno {
    pub id: String,
    pub nombre: String,
    pub app: App,
    pub datos: PathBuf,
    pub recursos: PathBuf,
    /// `<id>://localhost/` (Windows: `http://<id>.localhost/`).
    pub base: String,
    pub global: String,
    pub config: Config,
    pub idioma: Idioma,
    pub procesador: Procesador,
    pub fila: Fila,
    pub declaradas: BTreeMap<String, Accion>,
    pub errores: Vec<String>,
    opciones: Opciones,
    registradas: RwLock<HashMap<String, Registrada>>,
    inyectores: RwLock<HashMap<String, Inyector>>,
    medios: RwLock<HashMap<String, Resolver>>,
    ganchos: RwLock<Ganchos>,
    vigilante: Option<Vigilante>,
    notificaciones: Notificaciones,
    handle: OnceLock<AppHandle>,
    /// Las ventanas que ya mandaron «listo» (antes, nada se les manda).
    listas: Mutex<HashSet<String>>,
    /// Las ventanas agregadas que hablan con el puente.
    otras: Mutex<HashSet<String>>,
    soltados: Mutex<Vec<PathBuf>>,
    /// Lo que el host le pidió a la página y espera (`pedir`): id → quien espera.
    pedidos: Mutex<HashMap<String, mpsc::Sender<Value>>>,
    ocupadas: AtomicUsize,
    saliendo: AtomicBool,
    tareas: AtomicBool,
    mostrada: AtomicBool,
}

/// El host: se clona barato (es un `Arc`). Se pasa a cada acción propia.
#[derive(Clone)]
pub struct Host(pub Arc<Interno>);

impl std::ops::Deref for Host {
    type Target = Interno;
    fn deref(&self) -> &Interno {
        &self.0
    }
}

impl Host {
    /// Arma el host sin ventana (lo usa `arrancar` y las pruebas).
    pub fn nuevo(mut op: Opciones, recursos: PathBuf, identificador: &str) -> Result<Host, String> {
        let a = e::leer_app(&recursos)?;
        let datos = match op.datos.clone() {
            Some(d) => d,
            None => e::carpeta_datos(&a, &e::Sistema::actual())?,
        };
        let propia = a.datos.is_object();
        let visible = a.datos.as_str() == Some("visible") && op.datos.is_none();
        let d2 = datos.clone();
        let preparar = move || {
            let _ = e::preparar_carpeta(&d2, propia, visible);
        };
        let config = Config::nueva(datos.join("config.json"), a.config.clone(), Box::new(preparar));
        let idioma = Idioma::nuevo(&config, &recursos, op.idioma_elegido.take());
        let global = op.global.clone().unwrap_or_else(|| e::global_de(&a.id));
        if global.is_empty() || !global.starts_with(|c: char| c.is_ascii_uppercase()) || !global.chars().all(|c| c.is_ascii_alphanumeric()) {
            return Err("«global» es el nombre del objeto window.<App> (ej. «Ana»).".into());
        }
        let python = op.python.clone().unwrap_or_else(|| python_de(&recursos));
        let (declaradas, errores) = e::cargar_acciones(&recursos);
        for x in &errores {
            eprintln!("{}: {x}", a.nombre);
        }
        let vigilante = op.vigilar.clone().map(|ex| Vigilante::nuevo(Some(ex), None, None));
        let id = a.id.clone();
        let interno = Arc::new_cyclic(|debil: &std::sync::Weak<Interno>| {
            let d = debil.clone();
            let t = Arc::new(move |x: &str| d.upgrade().map(|h| h.idioma.t(&h.config, x)).unwrap_or_else(|| x.to_string()));
            let procesador = Procesador::nuevo(python, recursos.clone(), &id, datos.clone(), t).con_lector(op.lector_progreso.clone()).con_herramientas(herramientas_de(&recursos));
            Interno {
                id: id.clone(),
                nombre: a.nombre.clone(),
                base: protocolo::base(&id),
                global,
                procesador,
                fila: Fila::default(),
                declaradas,
                errores,
                registradas: RwLock::new(HashMap::new()),
                inyectores: RwLock::new(HashMap::new()),
                medios: RwLock::new(HashMap::new()),
                ganchos: RwLock::new(Ganchos::default()),
                vigilante,
                notificaciones: Notificaciones::nuevas(identificador),
                handle: OnceLock::new(),
                listas: Mutex::new(HashSet::new()),
                otras: Mutex::new(HashSet::new()),
                soltados: Mutex::new(Vec::new()),
                pedidos: Mutex::new(HashMap::new()),
                ocupadas: AtomicUsize::new(0),
                saliendo: AtomicBool::new(false),
                tareas: AtomicBool::new(false),
                mostrada: AtomicBool::new(false),
                app: a,
                datos,
                recursos,
                config,
                idioma,
                opciones: op,
            }
        });
        let host = Host(interno);
        host.preparar_inyectores();
        host.preparar_vigilante();
        Ok(host)
    }

    fn preparar_inyectores(&self) {
        let mut i = self.inyectores.write().expect("inyectores");
        i.insert("idiomaUI".into(), Arc::new(|_, h| Inyectado::Valor(json!(h.codigo_idioma()))));
        i.insert("carpetaDatos".into(), Arc::new(|_, h| Inyectado::Valor(json!(h.datos.to_string_lossy()))));
        if self.opciones.carpeta.is_some() {
            i.insert(
                "carpetaActual".into(),
                Arc::new(|_, h| match h.carpeta_actual() {
                    Some(c) => Inyectado::Valor(json!(c.to_string_lossy())),
                    None => Inyectado::Falta(Falta { texto: h.opciones.carpeta.as_ref().map(|c| c.falta.clone()).unwrap_or_default(), valores: json!({}) }),
                }),
            );
        }
    }

    fn preparar_vigilante(&self) {
        let Some(v) = &self.vigilante else { return };
        let debil = Arc::downgrade(&self.0);
        *v.al_cambiar_archivo.lock().expect("vigilante") = Some(Arc::new(move |ruta: &str, texto: &str| {
            if let Some(h) = debil.upgrade() {
                Host(h).llamar("archivoCambiado", json!({"ruta": ruta, "texto": texto}), None);
            }
        }));
    }

    // ───────────── Lo que usa la app ─────────────
    pub fn t(&self, x: &str) -> String {
        self.idioma.t(&self.config, x)
    }
    pub fn f(&self, x: &str, valores: &Value) -> String {
        self.idioma.f(&self.config, x, valores)
    }
    pub fn codigo_idioma(&self) -> String {
        self.idioma.codigo(&self.config)
    }
    pub fn idioma_elegido(&self) -> bool {
        self.idioma.elegido(&self.config)
    }
    pub fn handle(&self) -> Option<&AppHandle> {
        self.handle.get()
    }
    pub fn version(&self) -> String {
        self.handle().map(|h| h.package_info().version.to_string()).unwrap_or_else(|| self.app.version())
    }
    pub fn vigilante(&self) -> Option<&Vigilante> {
        self.vigilante.as_ref()
    }
    pub fn notificaciones(&self) -> &Notificaciones {
        &self.notificaciones
    }
    /// Los secretos de la app en el llavero del sistema (servicio = el nombre de la app, como en «host-mac»).
    pub fn secretos(&self, nombre: Option<&str>) -> Secretos {
        Secretos::nuevo(&match nombre {
            Some(n) => format!("{} · {n}", self.nombre),
            None => self.nombre.clone(),
        })
    }
    /// Una acción propia de la app. Gana sobre lo que trae el host y lo declarado: así se migra de a poco.
    pub fn registrar(&self, nombre: &str, f: impl Fn(Value, &Host, Ctx) + Send + Sync + 'static) {
        assert!(e::es_accion(nombre), "acción rara: {nombre}");
        self.registradas.write().expect("registradas").insert(nombre.into(), Arc::new(f));
    }
    /// Un valor para el `inyectar` de las acciones (lo tuyo gana sobre lo del host).
    pub fn inyector(&self, fuente: &str, f: impl Fn(&Map<String, Value>, &Host) -> Inyectado + Send + Sync + 'static) {
        self.inyectores.write().expect("inyectores").insert(fuente.into(), Arc::new(f));
    }
    /// `host.medio("video", ruta)` en la interfaz: `resolver(ruta)` devuelve la ruta absoluta que se puede servir, o None.
    pub fn registrar_medios(&self, nombre: &str, resolver: impl Fn(&str, &Host) -> Option<PathBuf> + Send + Sync + 'static) {
        let ok = !nombre.is_empty() && nombre.len() <= 30 && nombre != "ui" && nombre.starts_with(|c: char| c.is_ascii_lowercase())
            && nombre.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-');
        assert!(ok, "medios: nombre raro");
        self.medios.write().expect("medios").insert(nombre.into(), Arc::new(resolver));
    }
    pub fn al_estado(&self, f: impl Fn(Map<String, Value>, &Host) -> Map<String, Value> + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").estado = Some(Arc::new(f));
    }
    /// Lo que corre solo, una vez y recién con el idioma elegido.
    /// Justo después de mandarle el estado a la ventana principal (al abrir y con `enviar_estado`): p. ej. pedirle a la página algo
    /// que se arma con el estado recién llegado.
    pub fn despues_del_estado(&self, f: impl Fn(&Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").despues_del_estado = Some(Arc::new(f));
    }
    pub fn al_iniciar_tareas(&self, f: impl Fn(&Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").tareas = Some(Arc::new(f));
    }
    pub fn al_cambiar_config(&self, f: impl Fn(&Map<String, Value>, &Map<String, Value>, &Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").al_cambiar_config = Some(Arc::new(f));
    }
    pub fn antes_de_salir(&self, f: impl Fn(&Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").antes_de_salir = Some(Arc::new(f));
    }
    pub fn al_tocar_aviso(&self, f: impl Fn(&str, &Host) + Send + Sync + 'static) {
        let f: GanchoTocar = Arc::new(f);
        self.ganchos.write().expect("ganchos").al_tocar_aviso = Some(f.clone());
        let debil = Arc::downgrade(&self.0);
        *self.notificaciones.al_tocar.lock().expect("avisos") = Some(Arc::new(move |id: &str| {
            if let Some(h) = debil.upgrade() {
                let h = Host(h);
                h.mostrar();
                f(id, &h);
            }
        }));
    }
    pub fn al_soltar(&self, f: impl Fn(&[PathBuf], &Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").al_soltar = Some(Arc::new(f));
    }
    pub fn al_crear_ventana(&self, f: impl Fn(&WebviewWindow, &Host) + Send + Sync + 'static) {
        self.ganchos.write().expect("ganchos").al_crear_ventana = Some(Arc::new(f));
    }
    /// La ruta real de un archivo que la persona soltó, por su nombre (nunca una ruta armada con lo que manda la web).
    pub fn soltado(&self, nombre: &str) -> Option<PathBuf> {
        self.soltados.lock().ok()?.iter().find(|p| p.file_name().is_some_and(|n| n.to_string_lossy() == nombre)).cloned()
    }
    pub fn dentro(&self, base: &Path, relativa: &str, extensiones: Option<&[&str]>) -> Option<PathBuf> {
        e::dentro(base, relativa, extensiones)
    }
    pub fn falta(&self, texto: &str, valores: Value) -> Inyectado {
        Inyectado::Falta(Falta { texto: texto.into(), valores })
    }
    pub fn ocupar(&self) {
        self.ocupadas.fetch_add(1, Ordering::SeqCst);
    }
    pub fn soltar_ocupada(&self) {
        let mut x = self.ocupadas.load(Ordering::SeqCst);
        while x > 0 {
            match self.ocupadas.compare_exchange(x, x - 1, Ordering::SeqCst, Ordering::SeqCst) {
                Ok(_) => break,
                Err(y) => x = y,
            }
        }
    }
    /// Algo se cortaría si la app se cierra: un guardado en la fila, un script corriendo o algo que la app marcó.
    pub fn ocupada(&self) -> bool {
        self.fila.pendientes() > 0 || self.procesador.en_curso() > 0 || self.ocupadas.load(Ordering::SeqCst) > 0
    }
    /// Espera (hasta `ms`) a que no quede nada. true si quedó libre.
    pub fn esperar_libre(&self, ms: u64) -> bool {
        let limite = Instant::now() + Duration::from_millis(ms);
        thread::sleep(Duration::from_millis(300));
        while self.ocupada() && Instant::now() < limite {
            thread::sleep(Duration::from_millis(100));
        }
        !self.ocupada()
    }

    // ───────────── Hacia la interfaz ─────────────
    /// window.<App>.<funcion>(d) en la ventana principal (si ya mandó «listo») o, con `destino`, en otra ventana agregada.
    pub fn llamar(&self, funcion: &str, d: Value, destino: Option<&str>) -> bool {
        if !e::es_funcion(funcion) {
            return false;
        }
        let Some(h) = self.handle() else { return false };
        let etiqueta = destino.unwrap_or(PRINCIPAL);
        if etiqueta == PRINCIPAL {
            if !self.listas.lock().map(|l| l.contains(PRINCIPAL)).unwrap_or(false) {
                return false;
            }
        } else if !self.otras.lock().map(|o| o.contains(etiqueta)).unwrap_or(false) {
            return false;
        }
        let Some(w) = h.get_webview_window(etiqueta) else { return false };
        let g = &self.global;
        // El JSON va como argumento: nunca se arma código con lo que manda nadie.
        let js = format!("window.{g} && typeof window.{g}.{funcion} === \"function\" && window.{g}.{funcion}({})", d);
        let ok = w.eval(js).is_ok();
        if ok {
            anotar_registro(&format!("→ {etiqueta} {funcion}"));
        }
        ok
    }

    /// Le pide algo a la página principal y espera su respuesta (como `callAsyncJavaScript` en el Mac): llama
    /// `window.<App>.<funcion>({id, datos})` y la página, con `host.atender("<funcion>", async (datos) => …)` de «host-ui», responde
    /// por `respuestaPagina {id, respuesta}`. None si la página no está lista, no responde a tiempo o no atiende esa función.
    /// Bloquea: llámala desde una acción (cada una corre en su hilo), nunca desde el hilo de la ventana.
    pub fn pedir(&self, funcion: &str, datos: Value, limite: Duration) -> Option<Value> {
        let id = e::aleatorio_hex(16);
        let (tx, rx) = mpsc::channel();
        self.pedidos.lock().ok()?.insert(id.clone(), tx);
        let r = if self.llamar(funcion, json!({"id": id, "datos": datos}), None) { rx.recv_timeout(limite).ok() } else { None };
        if let Ok(mut p) = self.pedidos.lock() {
            p.remove(&id);
        }
        r.filter(|v| !v.is_null())
    }

    // ───────────── Acciones ─────────────
    /// Primero lo que registró la app, después lo que trae el host y al final lo declarado. Bloquea: corre en un hilo propio.
    pub fn despachar(&self, accion: &str, datos: Value, ctx: Ctx) {
        if !e::es_accion(accion) {
            return;
        }
        let d = if datos.is_object() { datos } else { json!({}) };
        let registrada = self.registradas.read().ok().and_then(|r| r.get(accion).cloned());
        if let Some(f) = registrada {
            return f(d, self, ctx);
        }
        if self.interna(accion, &d, &ctx) {
            return;
        }
        if let Some(def) = self.declaradas.get(accion).cloned() {
            self.correr_declarada(&def, d, ctx);
        }
    }

    /// Una acción declarada: validar → inyectar → (fila) → script con límite → eco → responder → después.
    fn correr_declarada(&self, def: &Accion, datos: Value, ctx: Ctx) -> Value {
        let responder = |r: Value, entrada: &Map<String, Value>| -> Value {
            if let Some(f) = &def.responde {
                let mut x = r.as_object().cloned().unwrap_or_default();
                for k in &def.eco {
                    if let Some(v) = entrada.get(k) {
                        x.insert(k.clone(), v.clone());
                    }
                }
                self.llamar(f, Value::Object(x), ctx.destino());
            }
            r
        };
        let mut entrada = match e::validar_datos(def, &datos) {
            Ok(x) => x,
            // Aunque los datos no pasen, vuelve el eco que sí es válido (la interfaz sabe a qué orden responde el error).
            Err(m) => {
                let r = json!({"ok": false, "codigo": "datos", "campo": m.campo, "texto": TEXTO_DATOS, "valores": {}, "error": self.t(TEXTO_DATOS)});
                return responder(r, &e::eco_valido(def, &datos));
            }
        };
        for (campo, fuente) in &def.inyectar {
            let f = fuente.as_str().and_then(|s| self.inyectores.read().ok().and_then(|i| i.get(s).cloned()));
            let valor = f.map(|f| f(&entrada, self));
            match valor {
                Some(Inyectado::Valor(v)) if !v.is_null() => {
                    entrada.insert(campo.clone(), v);
                }
                otro => {
                    let x = match otro {
                        Some(Inyectado::Falta(x)) => x,
                        _ => Falta { texto: TEXTO_FALTA.into(), valores: json!({}) },
                    };
                    let r = json!({"ok": false, "codigo": "falta", "campo": campo, "texto": x.texto, "valores": x.valores, "error": self.f(&x.texto, &x.valores)});
                    return responder(r, &entrada);
                }
            }
        }
        let tarea = || {
            let args = e::armar_args(def, &entrada);
            let mut o = OpcionesScript::default();
            match e::limite_de(def, &entrada) {
                Limite::Trabajo => o.latido = true,
                Limite::Segundos(s) => o.limite = Some(s),
            }
            if let Some(f) = def.progreso.clone() {
                let h = self.clone();
                o.progreso = Some(Box::new(move |eventos| {
                    h.llamar(&f, json!({"eventos": eventos}), None);
                }));
            }
            // «vigilar»: el vigilante conoce el texto que la app escribe ANTES de escribirlo (y el que lee, al leerlo).
            let ruta = match (&def.vigilar, &self.vigilante) {
                (Some(_), Some(_)) => entrada.get("ruta").and_then(Value::as_str).map(String::from),
                _ => None,
            };
            let v = self.vigilante.as_ref();
            let antes = ruta.as_ref().and_then(|r| v.and_then(|v| v.conocido(r)));
            let escribe = def.vigilar.as_deref() == Some("escribe");
            if let (Some(r), Some(v), true) = (&ruta, v, escribe) {
                v.conocer(r, entrada.get("texto").and_then(Value::as_str));
            }
            let r = if def.entrada_archivo {
                self.procesador.con_entrada(&def.script, &args, Value::Object(entrada.clone()), o)
            } else {
                self.procesador.correr_json(&def.script, &args, o)
            };
            if let (Some(ruta), Some(v)) = (&ruta, v) {
                let ok = r.get("ok") == Some(&Value::Bool(true));
                if def.vigilar.as_deref() == Some("lee") && ok {
                    if let Some(t) = r.get("texto").and_then(Value::as_str) {
                        v.conocer(ruta, Some(t));
                    }
                }
                if escribe && !ok {
                    v.conocer(ruta, antes.as_deref());
                }
            }
            r
        };
        let r = if def.cola_escritura { self.fila.agregar(tarea) } else { tarea() };
        let r = responder(r, &entrada);
        for x in &def.despues {
            if x != &def.nombre {
                self.despachar(x, json!({}), ctx.clone());
            }
        }
        r
    }

    /// Lo que trae el host (capacidades comunes). true si la atendió.
    fn interna(&self, accion: &str, d: &Value, ctx: &Ctx) -> bool {
        match accion {
            "listo" => {
                // Otra ventana agregada recibe su estado; la principal queda «lista» (antes, nada se le manda).
                let etiqueta = ctx.responder_a.clone().unwrap_or_else(|| PRINCIPAL.into());
                if let Ok(mut l) = self.listas.lock() {
                    l.insert(etiqueta.clone());
                }
                self.llamar("estado", Value::Object(self.estado()), ctx.destino());
                if ctx.responder_a.is_none() {
                    self.tras_el_estado();
                }
            }
            // La respuesta de la página a un `pedir`: solo de la ventana principal y solo para un pedido que sigue esperando.
            "respuestaPagina" => {
                if ctx.responder_a.is_none() {
                    let id = d["id"].as_str().unwrap_or("");
                    let tx = self.pedidos.lock().ok().and_then(|mut p| p.remove(id));
                    if let Some(tx) = tx {
                        let _ = tx.send(d.get("respuesta").cloned().unwrap_or(Value::Null));
                    }
                }
            }
            "config" => self.config_de_interfaz(d),
            // La franja de la barra transparente (puente_js): mover o agrandar la ventana que la tocó.
            "moverVentana" | "agrandarVentana" if self.franja() > 0.0 => {
                let etiqueta = ctx.responder_a.clone().unwrap_or_else(|| PRINCIPAL.into());
                if let Some(w) = self.handle().and_then(|a| a.get_webview_window(&etiqueta)) {
                    if accion == "moverVentana" {
                        let _ = w.start_dragging();
                    } else if w.is_maximized().unwrap_or(false) {
                        let _ = w.unmaximize();
                    } else {
                        let _ = w.maximize();
                    }
                }
            }
            "abrirEnlace" => {
                sistema::abrir_enlace(d.get("url").and_then(Value::as_str).unwrap_or(""));
            }
            "copiar" => {
                let ok = sistema::copiar(d.get("texto").and_then(Value::as_str).unwrap_or(""));
                self.llamar("copiado", json!({"ok": ok}), ctx.destino());
            }
            "buscarActualizacion" if self.opciones.actualizaciones.is_some() => {
                let a = self.opciones.actualizaciones.clone().expect("actualizaciones");
                self.llamar("actualizacionRevisada", a.revisar(&self.version()), None);
            }
            "actualizar" if self.opciones.actualizaciones.is_some() => {
                // La interfaz guarda todo justo antes de pedirlo: se espera. Nunca en medio de un guardado o de un script.
                if !self.esperar_libre(5000) {
                    self.llamar("actualizacionProgreso", json!({"paso": "error", "codigo": "ocupada", "texto": "Espera a que termine lo que está haciendo y vuelve a intentarlo.", "valores": {}, "total": 3}), None);
                } else {
                    let a = self.opciones.actualizaciones.clone().expect("actualizaciones");
                    a.instalar(self, &|p| {
                        self.llamar("actualizacionProgreso", p, None);
                    });
                }
            }
            _ => return false,
        }
        true
    }

    /// El estado: lo de bin/estado.py (si existe) + version, idioma, plataforma, config, actualizacion + lo de la app.
    pub fn estado(&self) -> Map<String, Value> {
        let script = match &self.opciones.estado_script {
            Some(s) => s.clone(),
            None => Some("estado.py".into()),
        };
        let mut base = Map::new();
        if let Some(s) = script.filter(|s| self.recursos.join("bin").join(s).exists()) {
            let correr = || {
                self.procesador.correr_json(&s, &[], OpcionesScript { limite: Some(self.opciones.limite_estado), ..Default::default() })
            };
            let r = if self.opciones.estado_en_fila { self.fila.agregar(correr) } else { correr() };
            base = p::sin_ok(r.as_object().cloned().unwrap_or_default());
        }
        base.insert("version".into(), json!(self.version()));
        base.insert("idioma".into(), json!(self.codigo_idioma()));
        base.insert("plataforma".into(), json!(e::plataforma()));
        if !base.contains_key("config") {
            base.insert("config".into(), Value::Object(self.config.leer()));
        }
        if let Some(a) = &self.opciones.actualizaciones {
            base.insert("actualizacion".into(), a.disponible());
        }
        let g = self.ganchos.read().ok().and_then(|g| g.estado.clone());
        match g {
            Some(f) => f(base, self),
            None => base,
        }
    }
    /// Los px de la franja que mueve la ventana (solo Mac con barra transparente).
    fn franja(&self) -> f64 {
        let v = &self.opciones.ventana;
        if cfg!(target_os = "macos") && v.barra_transparente { v.alto_franja.max(0.0) } else { 0.0 }
    }
    pub fn enviar_estado(&self) {
        self.llamar("estado", Value::Object(self.estado()), None);
        self.tras_el_estado();
    }
    fn tras_el_estado(&self) {
        let g = self.ganchos.read().ok().and_then(|g| g.despues_del_estado.clone());
        if let Some(f) = g {
            f(self);
        }
    }

    /// Lo que hace la acción `config` de la interfaz: guarda las claves de app.json (no las de `"interfaz": false`), rearma los
    /// menús si cambió el idioma, aplica la apariencia, avisa a `al_cambiar_config` y, con idioma elegido, parte las tareas. Para
    /// una app que registra su propio `config` (p. ej. para guardar ajustes con forma propia antes) y después sigue con esto.
    pub fn config_de_interfaz(&self, d: &Value) {
        let antes = self.config.leer();
        self.config.guardar(d, true);
        let ahora = self.config.leer();
        if antes.get("idioma_ui") != ahora.get("idioma_ui") {
            self.idioma.olvidar();
            self.armar_menu();
        }
        if antes.get("tema") != ahora.get("tema") {
            self.aplicar_tema();
        }
        let g = self.ganchos.read().ok().and_then(|g| g.al_cambiar_config.clone());
        if let Some(f) = g {
            f(&ahora, &antes, self);
        }
        if self.idioma_elegido() {
            self.iniciar_tareas();
        }
    }

    pub fn iniciar_tareas(&self) {
        if self.tareas.swap(true, Ordering::SeqCst) {
            return;
        }
        if let Some(a) = self.opciones.actualizaciones.clone() {
            let h = self.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_secs(15));
                loop {
                    let r = a.revisar(&h.version());
                    if r.get("hay") == Some(&Value::Bool(true)) {
                        h.llamar("actualizacionRevisada", r, None);
                    }
                    thread::sleep(Duration::from_secs(6 * 3600));
                }
            });
        }
        let g = self.ganchos.read().ok().and_then(|g| g.tareas.clone());
        if let Some(f) = g {
            let h = self.clone();
            thread::spawn(move || f(&h));
        }
    }

    // ───────────── La carpeta de la persona ─────────────
    /// La carpeta elegida, si todavía existe (ruta real), o None.
    pub fn carpeta_actual(&self) -> Option<PathBuf> {
        let c = self.opciones.carpeta.as_ref()?;
        let r = PathBuf::from(self.config.texto(&c.clave));
        if !r.is_absolute() || !r.is_dir() {
            return None;
        }
        std::fs::canonicalize(r).ok()
    }
    /// La deja como la actual (una ruta que eligió la persona o que la app leyó de lo suyo, nunca de la interfaz).
    pub fn usar_carpeta(&self, ruta: &Path) -> Option<PathBuf> {
        let c = self.opciones.carpeta.as_ref()?;
        let real = std::fs::canonicalize(ruta).ok().filter(|r| r.is_dir())?;
        self.config.guardar(&json!({ c.clave.clone(): real.to_string_lossy() }), false);
        if let Some(v) = &self.vigilante {
            v.empezar(&real);
        }
        Some(real)
    }
    /// El selector del sistema; None si la persona cancela.
    pub fn elegir_carpeta(&self) -> Option<PathBuf> {
        let c = self.opciones.carpeta.clone()?;
        let r = self.dialogo_carpeta(c.titulo.as_deref().map(|x| self.t(x)), self.carpeta_actual())?;
        self.usar_carpeta(&r)
    }
    pub fn olvidar_carpeta(&self) {
        if let Some(c) = &self.opciones.carpeta {
            self.config.guardar(&json!({ c.clave.clone(): "" }), false);
        }
        if let Some(v) = &self.vigilante {
            v.detener();
        }
    }

    // ───────────── Diálogos del sistema (en el hilo de la ventana, como piden Mac y GTK) ─────────────
    fn en_principal<T: Send + 'static>(&self, f: impl FnOnce() -> T + Send + 'static) -> Option<T> {
        let h = self.handle()?;
        let (tx, rx) = mpsc::channel();
        h.run_on_main_thread(move || {
            let _ = tx.send(f());
        })
        .ok()?;
        rx.recv().ok()
    }
    fn padre(&self) -> Option<WebviewWindow> {
        self.handle().and_then(|h| h.get_webview_window(PRINCIPAL))
    }
    pub fn dialogo_carpeta(&self, titulo: Option<String>, desde: Option<PathBuf>) -> Option<PathBuf> {
        let padre = self.padre();
        let r = self.en_principal(move || {
            let mut d = rfd::FileDialog::new();
            if let Some(t) = titulo {
                d = d.set_title(t);
            }
            if let Some(x) = desde {
                d = d.set_directory(x);
            }
            if let Some(w) = &padre {
                d = d.set_parent(w);
            }
            d.pick_folder()
        })??;
        std::fs::canonicalize(r).ok()
    }
    /// Archivos (rutas reales) o []. `extensiones`: ["md", "txt"].
    pub fn dialogo_archivos(&self, titulo: Option<String>, extensiones: &[&str], varios: bool, desde: Option<PathBuf>) -> Vec<PathBuf> {
        let padre = self.padre();
        let ext: Vec<String> = extensiones.iter().map(|x| x.to_string()).collect();
        let r = self.en_principal(move || {
            let mut d = rfd::FileDialog::new();
            if let Some(t) = titulo {
                d = d.set_title(t);
            }
            if !ext.is_empty() {
                d = d.add_filter(ext.join(", "), &ext);
            }
            if let Some(x) = desde {
                d = d.set_directory(x);
            }
            if let Some(w) = &padre {
                d = d.set_parent(w);
            }
            if varios { d.pick_files().unwrap_or_default() } else { d.pick_file().into_iter().collect() }
        });
        r.unwrap_or_default().into_iter().filter_map(|p| std::fs::canonicalize(p).ok()).collect()
    }
    /// «Guardar como»: escribe `contenido` de una vez donde la persona elija. Ok(ruta) o Err("cancelado" | "vacio" |
    /// "tamano" | "extension" | "escribir"). `privado`: el archivo queda solo para la persona (0600); sin decirlo, app.json.
    pub fn guardar_archivo(&self, sugerido: &str, extension: &str, contenido: &[u8], privado: Option<bool>) -> Result<PathBuf, &'static str> {
        self.guardar_archivo_con(sugerido, extension, contenido, ComoGuardar { privado, ..Default::default() })
    }
    /// Lo mismo, con más opciones: hasta cuánto pesa, en qué carpeta abre el diálogo y su título.
    pub fn guardar_archivo_con(&self, sugerido: &str, extension: &str, contenido: &[u8], como: ComoGuardar) -> Result<PathBuf, &'static str> {
        let ext: String = extension.chars().filter(|c| c.is_alphanumeric() || *c == '_').take(10).collect();
        if ext.is_empty() {
            return Err("extension");
        }
        if contenido.is_empty() {
            return Err("vacio");
        }
        if contenido.len() > como.maximo {
            return Err("tamano");
        }
        let nombre = e::nombre_archivo(sugerido, &ext);
        let padre = self.padre();
        let e2 = ext.clone();
        let desde = como.desde.filter(|d| d.is_dir()).or_else(dirs_documentos);
        let titulo = como.titulo.map(|t| self.t(&t));
        let r = self
            .en_principal(move || {
                let mut d = rfd::FileDialog::new().set_file_name(&nombre).add_filter(e2.to_uppercase(), &[e2.as_str()]);
                if let Some(x) = desde {
                    d = d.set_directory(x);
                }
                if let Some(t) = titulo {
                    d = d.set_title(t);
                }
                if let Some(w) = &padre {
                    d = d.set_parent(w);
                }
                d.save_file()
            })
            .flatten();
        let Some(mut destino) = r else { return Err("cancelado") };
        if !destino.to_string_lossy().to_lowercase().ends_with(&format!(".{}", ext.to_lowercase())) {
            destino.set_file_name(format!("{}.{ext}", destino.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()));
        }
        let solo = como.privado.unwrap_or_else(|| self.app.privado());
        e::escribir_atomico(&destino, contenido, if solo { 0o600 } else { 0o644 }).map_err(|_| "escribir")?;
        Ok(destino)
    }

    // ───────────── Ventana ─────────────
    pub fn ventana(&self) -> Option<WebviewWindow> {
        self.padre()
    }
    pub fn mostrar(&self) {
        let h = self.clone();
        if let Some(a) = self.handle() {
            let _ = a.run_on_main_thread(move || match h.padre() {
                Some(w) => {
                    let _ = w.unminimize();
                    let _ = w.show();
                    let _ = w.set_focus();
                }
                None => {
                    let _ = h.crear_ventana(true);
                }
            });
        }
    }
    /// Otra ventana con la misma interfaz (panel de la bandeja, barra flotante): habla con el puente con las mismas guardas y
    /// recibe la respuesta a lo que pidió. `pagina`: un archivo de ui/ («panel.html»).
    pub fn agregar_ventana(&self, etiqueta: &str, pagina: &str, ajustar: impl FnOnce(WebviewWindowBuilder<'_, Wry, AppHandle>) -> WebviewWindowBuilder<'_, Wry, AppHandle>) -> Option<WebviewWindow> {
        if etiqueta == PRINCIPAL || !e::es_accion(etiqueta) || protocolo::archivo_ui(&self.recursos.join("ui"), pagina).is_none() {
            return None;
        }
        let h = self.handle()?;
        let url = self.url(&format!("ui/{pagina}"))?;
        let b = self.preparar_web(WebviewWindowBuilder::new(h, etiqueta, WebviewUrl::CustomProtocol(url)));
        // Antes de crearla: su página puede mandar «listo» antes de que build() vuelva.
        self.otras.lock().ok()?.insert(etiqueta.into());
        let Ok(w) = ajustar(b).build() else {
            if let Ok(mut o) = self.otras.lock() {
                o.remove(etiqueta);
            }
            return None;
        };
        let h2 = self.clone();
        let et = etiqueta.to_string();
        w.on_window_event(move |ev| {
            if let WindowEvent::Destroyed = ev {
                if let Ok(mut o) = h2.otras.lock() {
                    o.remove(&et);
                }
                if let Ok(mut l) = h2.listas.lock() {
                    l.remove(&et);
                }
            }
        });
        Some(w)
    }

    fn url(&self, ruta: &str) -> Option<url::Url> {
        url::Url::parse(&format!("{}{ruta}", self.base)).ok()
    }

    /// Lo que lleva toda ventana con la interfaz: el puente, las guardas de navegación y nada de ventanas nuevas.
    fn preparar_web<'a>(&self, b: WebviewWindowBuilder<'a, Wry, AppHandle>) -> WebviewWindowBuilder<'a, Wry, AppHandle> {
        let ui = format!("{}ui/", self.base);
        let h = self.clone();
        let h2 = self.clone();
        let ui2 = ui.clone();
        // Un enlace https va por `abrirEnlace` (el de la app si lo registró: una app para niños solo abre su sitio).
        let enlace = move |h: &Host, u: &url::Url| {
            if u.scheme() == "https" {
                let h = h.clone();
                let url = u.to_string();
                thread::spawn(move || h.despachar("abrirEnlace", json!({"url": url}), Ctx::default()));
            }
        };
        let enlace2 = enlace;
        let mut b = b
            .initialization_script(puente_js(&self.id, &self.base, self.franja()))
            .on_navigation(move |u| {
                if u.as_str().starts_with(&ui) {
                    return true;
                }
                enlace(&h, u);
                false
            })
            .on_new_window(move |u, _| {
                if !u.as_str().starts_with(&ui2) {
                    enlace2(&h2, &u);
                }
                NewWindowResponse::Deny
            })
            .devtools(self.opciones.devtools);
        if !self.opciones.soltar {
            // La página recibe su `drop` de HTML como siempre (sin rutas).
            b = b.disable_drag_drop_handler();
        }
        b
    }

    fn crear_ventana(&self, mostrarla: bool) -> Option<WebviewWindow> {
        let h = self.handle()?;
        let v = &self.opciones.ventana;
        let g = e::leer_json(&self.datos.join(format!("{}.json", v.nombre)), 64 * 1024).unwrap_or(json!({}));
        let num = |k: &str| g.get(k).and_then(Value::as_f64).filter(|x| x.is_finite());
        let url = self.url("ui/index.html")?;
        let mut b = WebviewWindowBuilder::new(h, PRINCIPAL, WebviewUrl::CustomProtocol(url))
            .title(&self.nombre)
            .inner_size(num("width").filter(|x| *x >= v.min_ancho).unwrap_or(v.ancho), num("height").filter(|x| *x >= v.min_alto).unwrap_or(v.alto))
            .min_inner_size(v.min_ancho, v.min_alto)
            .visible(false)
            .decorations(v.marco)
            .theme(tema_de(&self.config.texto("tema")))
            .background_color(color(if self.oscuro() { &v.fondo_oscuro } else { &v.fondo_claro }));
        if let (Some(x), Some(y)) = (num("x"), num("y")) {
            b = b.position(x, y);
        }
        #[cfg(target_os = "macos")]
        if v.barra_transparente {
            b = b.title_bar_style(tauri::TitleBarStyle::Overlay).hidden_title(true);
        }
        if v.vidrio {
            use tauri::utils::config::WindowEffectsConfig;
            use tauri::window::Effect;
            b = b.transparent(true).effects(WindowEffectsConfig {
                effects: vec![if cfg!(windows) { Effect::Mica } else { Effect::Sidebar }],
                ..Default::default()
            });
        }
        let h2 = self.clone();
        b = self.preparar_web(b).on_page_load(move |w, p| {
            anotar_registro(&format!("página {}", if p.event() == PageLoadEvent::Finished { "cargada" } else { "cargando" }));
            // Una página nueva (o recargada) no está «lista» hasta que mande «listo» otra vez.
            if p.event() == PageLoadEvent::Started {
                if let Ok(mut l) = h2.listas.lock() {
                    l.remove(PRINCIPAL);
                }
            }
            if p.event() == PageLoadEvent::Finished && mostrarla && !h2.mostrada.swap(true, Ordering::SeqCst) {
                let _ = w.show();
                let _ = w.set_focus();
            }
        });
        // La ventana nueva no está «lista» hasta que su página mande «listo», que puede llegar antes de que build() vuelva: por
        // eso se olvida antes (y al empezar a cargar), nunca después.
        if let Ok(mut l) = self.listas.lock() {
            l.remove(PRINCIPAL);
        }
        let w = b.build().ok()?;
        let h3 = self.clone();
        w.on_window_event(move |ev| h3.evento_ventana(ev));
        let g = self.ganchos.read().ok().and_then(|g| g.al_crear_ventana.clone());
        if let Some(f) = g {
            f(&w, self);
        }
        Some(w)
    }

    fn guardar_lugar(&self) {
        let Some(w) = self.padre() else { return };
        let (Ok(f), Ok(pos), Ok(tam)) = (w.scale_factor(), w.outer_position(), w.inner_size()) else { return };
        if w.is_minimized().unwrap_or(false) || w.is_maximized().unwrap_or(false) || w.is_fullscreen().unwrap_or(false) {
            return;
        }
        let pos = pos.to_logical::<f64>(f);
        let tam = tam.to_logical::<f64>(f);
        let _ = e::preparar_carpeta(&self.datos, self.app.datos.is_object(), false);
        let d = json!({"x": pos.x, "y": pos.y, "width": tam.width, "height": tam.height});
        let _ = e::escribir_atomico(&self.datos.join(format!("{}.json", self.opciones.ventana.nombre)), d.to_string().as_bytes(), 0o600);
    }

    fn evento_ventana(&self, ev: &WindowEvent) {
        match ev {
            WindowEvent::CloseRequested { api, .. } => {
                self.guardar_lugar();
                if self.saliendo.load(Ordering::SeqCst) {
                    return;
                }
                api.prevent_close();
                match self.opciones.ventana.al_cerrar {
                    AlCerrar::Esconder => {
                        if let Some(w) = self.padre() {
                            let _ = w.hide();
                        }
                        self.llamar("menu", json!({"accion": "guardar"}), None);
                    }
                    AlCerrar::Salir => self.salir(),
                }
            }
            // Mientras se arrastra un archivo encima: la página no ve el arrastre (lo atiende el sistema), así que se le avisa
            // para que marque la zona donde soltar (`soltando {encima}`).
            WindowEvent::DragDrop(tauri::DragDropEvent::Enter { .. }) => {
                self.llamar("soltando", json!({"encima": true}), None);
            }
            WindowEvent::DragDrop(tauri::DragDropEvent::Leave) => {
                self.llamar("soltando", json!({"encima": false}), None);
            }
            WindowEvent::DragDrop(tauri::DragDropEvent::Drop { paths, .. }) => {
                self.llamar("soltando", json!({"encima": false}), None);
                let reales: Vec<PathBuf> = paths.iter().filter_map(|p| std::fs::canonicalize(p).ok()).collect();
                let nombres: Vec<String> = reales.iter().filter_map(|p| p.file_name().map(|n| n.to_string_lossy().into_owned())).collect();
                if let Ok(mut s) = self.soltados.lock() {
                    *s = reales.clone();
                }
                let g = self.ganchos.read().ok().and_then(|g| g.al_soltar.clone());
                if let Some(f) = g {
                    f(&reales, self);
                }
                self.llamar("soltados", json!({"nombres": nombres}), None);
            }
            WindowEvent::ThemeChanged(_) => self.aplicar_tema(),
            _ => {}
        }
    }

    fn oscuro(&self) -> bool {
        match self.config.texto("tema").as_str() {
            "oscuro" => true,
            "claro" => false,
            _ => self.padre().and_then(|w| w.theme().ok()).map(|t| t == Theme::Dark).unwrap_or(false),
        }
    }
    /// La barra de título, los menús y el fondo mientras carga siguen la apariencia elegida (pieza «tema»: config.tema).
    pub fn aplicar_tema(&self) {
        let tema = tema_de(&self.config.texto("tema"));
        if let Some(h) = self.handle() {
            h.set_theme(tema);
        }
        if let Some(w) = self.padre() {
            let v = &self.opciones.ventana;
            let _ = w.set_background_color(Some(color(if self.oscuro() { &v.fondo_oscuro } else { &v.fondo_claro })));
        }
    }

    /// Guarda, espera lo que está en curso, corta lo que siga y sale. Nada queda huérfano.
    pub fn salir(&self) {
        if self.saliendo.swap(true, Ordering::SeqCst) {
            return;
        }
        let h = self.clone();
        thread::spawn(move || {
            if h.opciones.guardar_al_salir {
                h.llamar("menu", json!({"accion": "guardar"}), None);
            }
            h.esperar_libre(3000);
            let g = h.ganchos.read().ok().and_then(|g| g.antes_de_salir.clone());
            if let Some(f) = g {
                f(&h);
            }
            if let Some(v) = &h.vigilante {
                v.detener();
            }
            h.procesador.cortar_todo();
            h.guardar_lugar();
            if let Some(a) = h.handle() {
                a.exit(0);
            }
        });
    }

    // ───────────── Menú ─────────────
    fn armar_menu(&self) {
        let Some(a) = self.handle().cloned() else { return };
        let h = self.clone();
        let _ = a.clone().run_on_main_thread(move || match h.menu(&a) {
            Ok(m) => {
                let _ = a.set_menu(m);
            }
            Err(x) => eprintln!("{}: menú: {x}", h.nombre),
        });
    }

    fn submenu(&self, a: &AppHandle, titulo: &str, items: &[ItemMenu]) -> tauri::Result<Submenu<Wry>> {
        self.submenu_constructor(a, titulo, items)?.build()
    }

    fn items_archivo(&self) -> Vec<ItemMenu> {
        let mut v = Vec::new();
        // Si la app ya puso «Ajustes…» en su lugar dentro de Archivo, el host no lo repite.
        let propio = self.opciones.menu.archivo.iter().any(|x| matches!(x, ItemMenu::Accion { accion, .. } if accion == "ajustes"));
        match if propio { &Some(None) } else { &self.opciones.titulo_ajustes } {
            Some(None) => {}
            Some(Some(t)) => v.push(item(t, "ajustes", Some("CmdOrCtrl+,"))),
            None => v.push(item("Ajustes…", "ajustes", Some("CmdOrCtrl+,"))),
        }
        v.extend(self.opciones.menu.archivo.iter().cloned());
        v
    }

    fn menu(&self, a: &AppHandle) -> tauri::Result<Menu<Wry>> {
        let salir = MenuItemBuilder::with_id("host:salir", self.f("Salir de {app}", &json!({"app": self.nombre}))).accelerator("CmdOrCtrl+Q").build(a)?;
        let mut m = MenuBuilder::new(a);
        let arriba = self.items_archivo();
        if cfg!(target_os = "macos") {
            // Mac: el menú de la app (con Ajustes y Salir), y Archivo solo si la app suma algo propio.
            let mut s = SubmenuBuilder::new(a, &self.nombre);
            for x in &arriba {
                if let ItemMenu::Accion { etiqueta, accion, atajo } = x {
                    if accion == "ajustes" {
                        let mut b = MenuItemBuilder::with_id(format!("pieza:{accion}"), self.t(etiqueta));
                        if let Some(k) = atajo {
                            b = b.accelerator(k);
                        }
                        s = s.item(&b.build(a)?);
                    }
                }
            }
            s = s
                .separator()
                .item(&PredefinedMenuItem::hide(a, Some(&self.f("Ocultar {app}", &json!({"app": self.nombre}))))?)
                .item(&PredefinedMenuItem::hide_others(a, Some(&self.t("Ocultar otras")))?)
                .separator()
                .item(&salir);
            m = m.item(&s.build()?);
            let propios: Vec<ItemMenu> = arriba.into_iter().filter(|x| !matches!(x, ItemMenu::Accion { accion, .. } if accion == "ajustes")).collect();
            if !propios.is_empty() {
                m = m.item(&self.submenu(a, "Archivo", &propios)?);
            }
        } else {
            let mut items = arriba;
            if !items.is_empty() {
                items.push(ItemMenu::Separador);
            }
            let mut s = self.submenu_constructor(a, "Archivo", &items)?;
            s = s.item(&salir);
            m = m.item(&s.build()?);
        }
        let mut edicion = SubmenuBuilder::new(a, self.t("Edición"));
        edicion = if self.opciones.menu.deshacer_propio {
            edicion
                .item(&MenuItemBuilder::with_id("pieza:deshacer", self.t("Deshacer")).accelerator("CmdOrCtrl+Z").build(a)?)
                .item(&MenuItemBuilder::with_id("pieza:rehacer", self.t("Rehacer")).accelerator("CmdOrCtrl+Shift+Z").build(a)?)
        } else {
            edicion.item(&PredefinedMenuItem::undo(a, Some(&self.t("Deshacer")))?).item(&PredefinedMenuItem::redo(a, Some(&self.t("Rehacer")))?)
        };
        let edicion = edicion
            .separator()
            .item(&PredefinedMenuItem::cut(a, Some(&self.t("Cortar")))?)
            .item(&PredefinedMenuItem::copy(a, Some(&self.t("Copiar")))?)
            .item(&PredefinedMenuItem::paste(a, Some(&self.t("Pegar")))?)
            .item(&PredefinedMenuItem::select_all(a, Some(&self.t("Seleccionar todo")))?)
            .build()?;
        m = m.item(&edicion);
        let mut ver = self.submenu_constructor(a, "Ver", &self.opciones.menu.ver)?;
        if !self.opciones.menu.ver.is_empty() {
            ver = ver.separator();
        }
        ver = ver.item(&PredefinedMenuItem::fullscreen(a, Some(&self.t("Pantalla completa")))?);
        m = m.item(&ver.build()?);
        for (t, items) in &self.opciones.menu.extra {
            m = m.item(&self.submenu(a, t, items)?);
        }
        if cfg!(target_os = "macos") {
            let v = SubmenuBuilder::new(a, self.t("Ventana"))
                .item(&PredefinedMenuItem::minimize(a, Some(&self.t("Minimizar")))?)
                .item(&PredefinedMenuItem::close_window(a, Some(&self.t("Cerrar ventana")))?)
                .build()?;
            m = m.item(&v);
        }
        if self.opciones.ayuda && (self.opciones.sitio.is_some() || self.opciones.codigo.is_some()) {
            let mut s = SubmenuBuilder::new(a, self.t("Ayuda"));
            if self.opciones.sitio.is_some() {
                s = s.item(&MenuItemBuilder::with_id("host:sitio", self.f("Sitio de {app}", &json!({"app": self.nombre}))).build(a)?);
            }
            if self.opciones.codigo.is_some() {
                s = s.item(&MenuItemBuilder::with_id("host:codigo", self.t("Código")).build(a)?);
            }
            m = m.item(&s.build()?);
        }
        m.build()
    }

    fn submenu_constructor<'a>(&self, a: &'a AppHandle, titulo: &str, items: &[ItemMenu]) -> tauri::Result<SubmenuBuilder<'a, Wry, AppHandle>> {
        let mut s = SubmenuBuilder::new(a, self.t(titulo));
        for (i, x) in items.iter().enumerate() {
            s = match x {
                ItemMenu::Separador => s.separator(),
                ItemMenu::Accion { etiqueta, accion, atajo } => {
                    let mut m = MenuItemBuilder::with_id(format!("pieza:{accion}"), self.t(etiqueta));
                    if let Some(k) = atajo {
                        m = m.accelerator(k);
                    }
                    s.item(&m.build(a)?)
                }
                ItemMenu::Nativo { etiqueta, atajo, .. } => {
                    let mut m = MenuItemBuilder::with_id(format!("nativo:{titulo}:{i}"), self.t(etiqueta));
                    if let Some(k) = atajo {
                        m = m.accelerator(k);
                    }
                    s.item(&m.build(a)?)
                }
            };
        }
        Ok(s)
    }

    fn al_menu(&self, id: &str) {
        if let Some(accion) = id.strip_prefix("pieza:") {
            // Nada antes de elegir el idioma.
            if !self.idioma_elegido() {
                return;
            }
            self.mostrar();
            self.llamar("menu", json!({"accion": accion}), None);
            return;
        }
        if let Some(resto) = id.strip_prefix("nativo:") {
            if let Some((titulo, i)) = resto.rsplit_once(':') {
                let todos: Vec<(String, Vec<ItemMenu>)> = [("Archivo".to_string(), self.items_archivo()), ("Ver".to_string(), self.opciones.menu.ver.clone())]
                    .into_iter()
                    .chain(self.opciones.menu.extra.iter().cloned())
                    .collect();
                let f = todos.iter().find(|(t, _)| t == titulo).and_then(|(_, l)| i.parse::<usize>().ok().and_then(|i| l.get(i)));
                if let Some(ItemMenu::Nativo { f, .. }) = f {
                    let (f, h) = (f.clone(), self.clone());
                    thread::spawn(move || f(&h));
                }
            }
            return;
        }
        match id {
            "host:salir" => self.salir(),
            "host:mostrar" => self.mostrar(),
            "host:sitio" => {
                sistema::abrir_enlace(self.opciones.sitio.as_deref().unwrap_or(""));
            }
            "host:codigo" => {
                sistema::abrir_enlace(self.opciones.codigo.as_deref().unwrap_or(""));
            }
            _ => {}
        }
    }

    fn crear_bandeja(&self, a: &AppHandle) -> tauri::Result<()> {
        use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
        let menu = MenuBuilder::new(a)
            .item(&MenuItemBuilder::with_id("host:mostrar", self.f("Abrir {app}", &json!({"app": self.nombre}))).build(a)?)
            .separator()
            .item(&MenuItemBuilder::with_id("host:salir", self.f("Salir de {app}", &json!({"app": self.nombre}))).build(a)?)
            .build()?;
        let mut b = TrayIconBuilder::with_id("pieza").tooltip(&self.nombre).menu(&menu).show_menu_on_left_click(false);
        if let Some(i) = a.default_window_icon() {
            b = b.icon(i.clone());
        }
        let h = self.clone();
        b.on_tray_icon_event(move |_, ev| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = ev {
                h.mostrar();
            }
        })
        .build(a)?;
        Ok(())
    }

    fn abrir_al_arrancar(&self) -> bool {
        self.opciones.abrir_al_arrancar.unwrap_or_else(|| !std::env::args().any(|x| x == "--oculta"))
    }

    // ───────────── El protocolo propio ─────────────
    fn servir(&self, req: &tauri::http::Request<Vec<u8>>) -> protocolo::Respuesta {
        let u = req.uri();
        if u.query().is_some() {
            return protocolo::no();
        }
        let camino = u.path().trim_start_matches('/');
        let (primero, resto) = camino.split_once('/').unwrap_or((camino, ""));
        if primero == "ui" {
            return match protocolo::archivo_ui(&self.recursos.join("ui"), resto) {
                Some(r) => protocolo::servir_archivo(&r, None),
                None => protocolo::no(),
            };
        }
        let resolver = self.medios.read().ok().and_then(|m| m.get(primero).cloned());
        let (Some(f), Some(rel)) = (resolver, protocolo::decodificar(resto)) else { return protocolo::no() };
        match f(&rel, self) {
            Some(a) if a.is_absolute() => {
                let rango = req.headers().get("range").and_then(|v| v.to_str().ok());
                protocolo::servir_archivo(&a, rango)
            }
            _ => protocolo::no(),
        }
    }
}

/// El puente que ve la página: `window.<ID>_HOST` (la plataforma), `window.<ID>_BASE` (para `host.medio`) y
/// `window.<id>Escritorio.enviar(msg)`, lo mismo que espera la pieza «host-ui». Copia JSON: a la app nunca llega un objeto
/// de la página. Solo en el marco principal.
pub fn puente_js(id: &str, base: &str, franja: f64) -> String {
    let mayus = id.to_uppercase();
    let plat = e::plataforma();
    // La franja de arriba que mueve la ventana (Mac, barra transparente): arrastrar la mueve y doble clic la agranda, salvo sobre
    // algo que se toca.
    let franja = if franja > 0.0 {
        format!(
            r#"
  var tocable = "button, a, input, select, textarea, label, summary, [role=button], [contenteditable], [data-sin-franja]";
  var moverVentana = function (accion) {{ return function (ev) {{
    if (ev.button !== 0 || ev.clientY > {franja} || (ev.target && ev.target.closest && ev.target.closest(tocable))) return;
    window.{id}Escritorio.enviar({{ accion: accion, datos: {{}} }});
  }}; }};
  window.addEventListener("mousedown", function (ev) {{ if (ev.detail === 1) moverVentana("moverVentana")(ev); }}, true);
  window.addEventListener("dblclick", moverVentana("agrandarVentana"), true);"#
        )
    } else {
        String::new()
    };
    format!(
        r#"(function () {{
  if (window.top !== window) return;
  var fijo = function (k, v) {{ try {{ Object.defineProperty(window, k, {{ value: v, writable: false, configurable: false, enumerable: false }}); }} catch (e) {{}} }};
  fijo("{mayus}_HOST", "{plat}");
  fijo("{mayus}_BASE", "{base}");
  fijo("{id}Escritorio", Object.freeze({{
    enviar: function (msg) {{
      try {{
        var i = window.__TAURI_INTERNALS__;
        if (i && typeof i.invoke === "function") i.invoke("pieza", {{ msg: JSON.parse(JSON.stringify(msg)) }}).catch(function () {{}});
      }} catch (e) {{}}
    }}
  }}));{franja}
}})();"#
    )
}

/// El único comando que la página puede pedir: solo de una ventana propia y con su página en ui/.
#[tauri::command]
fn pieza(webview: tauri::Webview, msg: Value, estado: tauri::State<'_, Host>) {
    let host: Host = estado.inner().clone();
    let etiqueta = webview.label().to_string();
    let propia = etiqueta == PRINCIPAL || host.otras.lock().map(|o| o.contains(&etiqueta)).unwrap_or(false);
    let en_ui = webview.url().map(|u| u.as_str().starts_with(&format!("{}ui/", host.base))).unwrap_or(false);
    if !propia || !en_ui {
        anotar_registro(&format!("rechazado {etiqueta}"));
        return;
    }
    let Some(accion) = msg.get("accion").and_then(Value::as_str).filter(|a| e::es_accion(a)).map(String::from) else { return };
    anotar_registro(&format!("{etiqueta} {accion}"));
    let datos = msg.get("datos").filter(|d| d.is_object()).cloned().unwrap_or(json!({}));
    let ctx = Ctx { responder_a: (etiqueta != PRINCIPAL).then_some(etiqueta) };
    thread::spawn(move || host.despachar(&accion, datos, ctx));
}

/// Para la prueba de arranque (escritorio/pruebas/arranque.sh): con PIEZA_REGISTRO=<archivo>, el host anota ahí el nombre de
/// cada acción que llega por el puente (solo el nombre, nunca los datos) y cuándo carga la página. Sin la variable, nada.
fn anotar_registro(linea: &str) {
    if let Some(r) = std::env::var_os("PIEZA_REGISTRO") {
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(r) {
            let _ = writeln!(f, "{linea}");
        }
    }
}

/// Arranca la app: arma el host, deja registrar lo propio (`configurar`), instala menús, aplica la apariencia y abre la
/// ventana. Lo que corre solo espera al idioma elegido. Al salir, la interfaz guarda y se espera la fila (3 s).
pub fn arrancar(contexto: tauri::Context<Wry>, op: Opciones, configurar: impl FnOnce(&Host)) {
    let identificador = contexto.config().identifier.clone();
    let recursos = match op.recursos.clone() {
        Some(r) => r,
        None => recursos_de(&contexto).unwrap_or_else(|x| fallar(&x)),
    };
    let host = Host::nuevo(op, recursos, &identificador).unwrap_or_else(|x| fallar(&x));
    configurar(&host);
    let id = host.id.clone();
    let h_protocolo = host.clone();
    let h_instancia = host.clone();
    let h_setup = host.clone();
    let h_menu = host.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(move |_, _, _| h_instancia.mostrar()))
        .manage(host.clone())
        .register_asynchronous_uri_scheme_protocol(id, move |_ctx, req, responder| {
            let h = h_protocolo.clone();
            thread::spawn(move || {
                let r = h.servir(&req);
                anotar_registro(&format!("sirve {} {}", r.estado, req.uri().path()));
                let mut b = tauri::http::Response::builder().status(r.estado);
                for (k, v) in r.cabeceras {
                    b = b.header(k, v);
                }
                responder.respond(b.body(r.cuerpo).unwrap_or_default());
            });
        })
        .invoke_handler(tauri::generate_handler![pieza])
        .on_menu_event(move |_, ev| h_menu.al_menu(ev.id().as_ref()))
        .setup(move |app| {
            let h = h_setup;
            let _ = h.handle.set(app.handle().clone());
            let _ = e::preparar_carpeta(&h.datos, h.app.datos.is_object(), h.app.datos.as_str() == Some("visible") && h.opciones.datos.is_none());
            if let Ok(mut s) = h.idioma.sistema.lock() {
                *s = sys_locale::get_locale().unwrap_or_else(|| "es".into());
            }
            #[cfg(target_os = "macos")]
            if h.opciones.solo_barra_de_menu {
                app.set_activation_policy(tauri::ActivationPolicy::Accessory);
            }
            h.aplicar_tema();
            match h.menu(app.handle()) {
                Ok(m) => {
                    let _ = app.set_menu(m);
                }
                Err(x) => eprintln!("{}: menú: {x}", h.nombre),
            }
            if h.opciones.bandeja || h.opciones.solo_barra_de_menu || h.opciones.ventana.al_cerrar == AlCerrar::Esconder {
                if let Err(x) = h.crear_bandeja(app.handle()) {
                    eprintln!("{}: bandeja: {x}", h.nombre);
                }
            }
            if let (Some(v), Some(c)) = (&h.vigilante, h.carpeta_actual()) {
                v.empezar(&c);
            }
            h.crear_ventana(h.abrir_al_arrancar());
            if h.idioma_elegido() {
                h.iniciar_tareas();
            }
            Ok(())
        })
        .build(contexto)
        .unwrap_or_else(|x| fallar(&x.to_string()));
    let h = host;
    app.run(move |_, ev| {
        if let RunEvent::ExitRequested { api, code, .. } = ev {
            // Cerrar sesión, apagar el equipo, ⌘Q del sistema: igual guarda y sale. `exit(0)` del host trae `code`.
            if code.is_none() && !h.saliendo.load(Ordering::SeqCst) {
                if h.opciones.ventana.al_cerrar == AlCerrar::Esconder && h.padre().is_some() {
                    api.prevent_exit();
                    return;
                }
                api.prevent_exit();
                h.salir();
            }
        }
    });
}

fn fallar(x: &str) -> ! {
    eprintln!("{x}");
    std::process::exit(1)
}

/// Empaquetada, el código va en `recursos/` junto a los recursos de Tauri (Mac: Contents/Resources/recursos; Windows: junto al
/// .exe; Linux: /usr/lib/<App>/recursos o, con instalar.sh, junto al ejecutable). En desarrollo, la raíz del repo.
fn recursos_de(contexto: &tauri::Context<Wry>) -> Result<PathBuf, String> {
    let _ = contexto;
    let es_la_app = |d: &Path| e::leer_app(d).is_ok() && d.join("ui").is_dir();
    // Desarrollo (cargo run): el código vivo del repo, no la copia que Tauri deja junto al ejecutable.
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
    if cfg!(debug_assertions) && es_la_app(&dev) {
        return Ok(std::fs::canonicalize(&dev).unwrap_or(dev));
    }
    if let Ok(exe) = std::env::current_exe() {
        let dir = exe.parent().map(Path::to_path_buf).unwrap_or_default();
        let mut candidatos = vec![dir.join("recursos"), dir.join("../Resources/recursos")];
        if let Ok(l) = std::fs::read_dir(dir.join("../lib")) {
            candidatos.extend(l.flatten().map(|d| d.path().join("recursos")));
        }
        if let Some(c) = candidatos.into_iter().find(|c| es_la_app(c)) {
            return Ok(std::fs::canonicalize(&c).unwrap_or(c));
        }
    }
    if es_la_app(&dev) {
        return Ok(std::fs::canonicalize(&dev).unwrap_or(dev));
    }
    Err("No encontré app.json dentro de la app (recursos/app.json).".into())
}

/// Python portátil que viene con la app; en desarrollo (sin escritorio/vendor/), el del sistema.
pub fn python_de(recursos: &Path) -> PathBuf {
    let exe = if cfg!(windows) { "python.exe" } else { "bin/python3" };
    let mut candidatos = vec![recursos.join("..").join("python").join(exe)];
    let vendor = match e::plataforma() {
        "mac" => "mac",
        "windows" => "win",
        _ => "linux",
    };
    candidatos.push(recursos.join("escritorio").join("vendor").join(vendor).join("python").join(exe));
    candidatos.into_iter().find(|p| p.exists()).unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }))
}

/// La carpeta de los programas que trae la app (ffmpeg, whisper-cli…), junto a Python; en desarrollo,
/// `escritorio/vendor/<os>/herramientas` si ya se armó con `preparar.sh`. None si no hay.
pub fn herramientas_de(recursos: &Path) -> Option<PathBuf> {
    let vendor = match e::plataforma() {
        "mac" => "mac",
        "windows" => "win",
        _ => "linux",
    };
    [recursos.join("..").join("herramientas"), recursos.join("escritorio").join("vendor").join(vendor).join("herramientas")]
        .into_iter()
        .find(|p| p.is_dir())
        .map(|p| std::fs::canonicalize(&p).unwrap_or(p))
}

fn dirs_documentos() -> Option<PathBuf> {
    let d = e::casa().join("Documents");
    d.is_dir().then_some(d)
}

fn tema_de(v: &str) -> Option<Theme> {
    match v {
        "claro" => Some(Theme::Light),
        "oscuro" => Some(Theme::Dark),
        _ => None,
    }
}

fn color(hex: &str) -> tauri::window::Color {
    let h = hex.trim_start_matches('#');
    let c = |i: usize| h.get(i..i + 2).and_then(|x| u8::from_str_radix(x, 16).ok()).unwrap_or(0);
    tauri::window::Color(c(0), c(2), c(4), 255)
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn app() -> (PathBuf, Host) {
        let d = std::env::temp_dir().join(format!("pieza-host-{}", e::aleatorio_hex(4)));
        std::fs::create_dir_all(d.join("bin")).unwrap();
        std::fs::create_dir_all(d.join("ui")).unwrap();
        std::fs::write(d.join("app.json"), r#"{"id": "ana", "nombre": "Ana", "config": {"idioma_ui": ["es", "en"]}}"#).unwrap();
        std::fs::write(
            d.join("bin/eco.py"),
            "import json,sys\nd=json.load(open(sys.argv[-2]))\njson.dump({'ok':True,'t':d.get('t'),'idioma':d.get('idioma')},open(sys.argv[-1],'w'))\n",
        )
        .unwrap();
        std::fs::write(
            d.join("acciones.json"),
            r#"{"formato": 1, "acciones": {"eco": {"script": "eco.py", "datos": {"t": {"tipo": "texto", "max": 5}}, "inyectar": {"idioma": "idiomaUI"},
                "entrada": "archivo", "limite": 10, "responde": "eco"}}}"#,
        )
        .unwrap();
        let op = Opciones { datos: Some(d.join("datos")), python: Some("python3".into()), ..Default::default() };
        let h = Host::nuevo(op, d.clone(), "cl.ana.prueba").unwrap();
        (d, h)
    }

    #[test]
    fn declarada_valida_inyecta_y_corre() {
        let (_d, h) = app();
        assert!(h.errores.is_empty(), "{:?}", h.errores);
        let def = h.declaradas.get("eco").cloned().unwrap();
        let r = h.correr_declarada(&def, json!({"t": "hola"}), Ctx::default());
        assert_eq!(r["t"], "hola");
        assert_eq!(r["idioma"], "es");
        let r = h.correr_declarada(&def, json!({"t": "demasiado largo"}), Ctx::default());
        assert_eq!(r["codigo"], "datos");
    }

    #[test]
    fn registrada_gana() {
        let (_d, h) = app();
        let (tx, rx) = mpsc::channel();
        h.registrar("eco", move |d, _, _| {
            let _ = tx.send(d);
        });
        h.despachar("eco", json!({"x": 1}), Ctx::default());
        assert_eq!(rx.recv().unwrap()["x"], 1);
    }

    #[test]
    fn estado_y_puente() {
        let (_d, h) = app();
        let e = h.estado();
        assert_eq!(e["idioma"], "es");
        assert!(e.contains_key("config"));
        let js = puente_js("ana", "ana://localhost/", 0.0);
        assert!(js.contains("ANA_HOST") && js.contains("anaEscritorio") && js.contains("window.top !== window"));
        assert!(!js.contains("moverVentana"));
        let js = puente_js("ana", "ana://localhost/", 30.0);
        assert!(js.contains("ev.clientY > 30") && js.contains("moverVentana") && js.contains("agrandarVentana"));
    }
}
