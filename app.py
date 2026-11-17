
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from conexion import conectar
from io import BytesIO
from datetime import datetime
from flask import send_file

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import cm
from xml.sax.saxutils import escape
app = Flask(__name__)
app.secret_key = "cambia_esta_clave_por_una_segura"


# Proteger las páginas que requieren iniciar sesión
def requiere_login(funcion):
    @wraps(funcion)
    def decorada(*args, **kwargs):
        if "id_usuario" not in session:
            flash("Debes iniciar sesión para continuar.")
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)
    return decorada


# Página de inicio
@app.route("/")
def inicio():
    return render_template("inicio.html")


# Registro de usuarios
@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        cedula = request.form["cedula"].strip()
        telefono = request.form.get("telefono", "").strip()
        correo = request.form["correo"].strip().lower()
        contrasena = request.form["contrasena"]
        tipo_usuario = request.form["tipo_usuario"]
        ubicacion = request.form.get("ubicacion", "").strip()

        if not all([nombre, cedula, correo, contrasena, tipo_usuario]):
            flash("Completa los campos obligatorios.")
            return redirect(url_for("registro"))

        if tipo_usuario not in ("habitante", "empleador"):
            flash("Selecciona un tipo de usuario válido.")
            return redirect(url_for("registro"))

        if len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.")
            return redirect(url_for("registro"))

        conexion = conectar()
        if conexion is None:
            flash("No se pudo conectar con la base de datos.")
            return redirect(url_for("registro"))

        cursor = None
        try:
            cursor = conexion.cursor()
            contrasena_hash = generate_password_hash(contrasena)

            cursor.execute("""
                INSERT INTO usuarios
                (nombre, cedula, telefono, correo, contraseña,
                 tipo_usuario, ubicacion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                nombre, cedula, telefono, correo,
                contrasena_hash, tipo_usuario, ubicacion
            ))

            conexion.commit()
            flash("Registro exitoso. Ya puedes iniciar sesión.")
            return redirect(url_for("login"))

        except Exception as e:
            conexion.rollback()
            print("Error en el registro:", e)
            flash("No se pudo registrar. Revisa si el correo o la cédula ya existen.")
            return redirect(url_for("registro"))

        finally:
            if cursor is not None:
                cursor.close()
            conexion.close()

    return render_template("registro.html")


@app.route("/publicar-empleo", methods=["GET", "POST"])
@requiere_login
def publicar_empleo():
    if session["tipo_usuario"] != "empleador":
        flash("Solo los empleadores pueden publicar ofertas de empleo.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        titulo = request.form["titulo"].strip()
        descripcion = request.form["descripcion"].strip()
        categoria = request.form["categoria"].strip()
        ubicacion = request.form["ubicacion"].strip()
        salario = request.form.get("salario", "").strip()
        tipo_contrato = request.form["tipo_contrato"].strip()

        if not titulo or not descripcion or not categoria or not ubicacion:
            flash("Completa todos los campos obligatorios.")
            return render_template("publicar_empleo.html")

        try:
            conexion = conectar()
            cursor = conexion.cursor()

            sql = """
                INSERT INTO empleos
                (id_empleador, titulo, descripcion, categoria,
                 ubicacion, salario, tipo_contrato)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            valores = (
                session["id_usuario"],
                titulo,
                descripcion,
                categoria,
                ubicacion,
                float(salario) if salario else None,
                tipo_contrato
            )

            cursor.execute(sql, valores)
            conexion.commit()

            cursor.close()
            conexion.close()

            flash("¡Oferta de empleo publicada correctamente!")
            return redirect(url_for("dashboard"))

        except Exception as e:
            flash("No se pudo publicar la oferta. Revisa los datos e inténtalo nuevamente.")
            print("Error al publicar empleo:", e)

    return render_template("publicar_empleo.html")


@app.route("/mis-empleos")
@requiere_login
def mis_empleos():
    if session["tipo_usuario"] != "empleador":
        flash("Esta sección es solo para empleadores.")
        return redirect(url_for("dashboard"))

    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT id_empleo, titulo, descripcion, categoria,
               ubicacion, salario, tipo_contrato,
               fecha_publicacion, estado
        FROM empleos
        WHERE id_empleador = %s
        ORDER BY fecha_publicacion DESC
    """, (session["id_usuario"],))

    empleos = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template("mis_empleos.html", empleos=empleos)


@app.route("/cerrar-empleo/<int:id_empleo>", methods=["POST"])
@requiere_login
def cerrar_empleo(id_empleo):
    if session["tipo_usuario"] != "empleador":
        flash("Solo los empleadores pueden cerrar ofertas.")
        return redirect(url_for("dashboard"))

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE empleos
        SET estado = 'cerrado'
        WHERE id_empleo = %s
          AND id_empleador = %s
          AND estado = 'disponible'
    """, (id_empleo, session["id_usuario"]))

    conexion.commit()
    actualizado = cursor.rowcount

    cursor.close()
    conexion.close()

    if actualizado:
        flash("La oferta se cerró correctamente.")
    else:
        flash("No se encontró una oferta disponible que puedas cerrar.")

    return redirect(url_for("mis_empleos"))

# Inicio de sesión real
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form["correo"].strip().lower()
        contrasena = request.form["contrasena"]

        conexion = conectar()
        if conexion is None:
            flash("No se pudo conectar con la base de datos.")
            return redirect(url_for("login"))

        cursor = None
        try:
            cursor = conexion.cursor(dictionary=True)
            cursor.execute("""
                SELECT id_usuario, nombre, correo, contraseña, tipo_usuario
                FROM usuarios
                WHERE correo = %s AND estado = TRUE
            """, (correo,))

            usuario = cursor.fetchone()

            if usuario and check_password_hash(
                usuario["contraseña"], contrasena
            ):
                session.clear()
                session["id_usuario"] = usuario["id_usuario"]
                session["nombre"] = usuario["nombre"]
                session["tipo_usuario"] = usuario["tipo_usuario"]

                return redirect(url_for("dashboard"))

            flash("Correo o contraseña incorrectos.")
            return redirect(url_for("login"))

        except Exception as e:
            print("Error en el inicio de sesión:", e)
            flash("Ocurrió un error al iniciar sesión.")
            return redirect(url_for("login"))

        finally:
            if cursor is not None:
                cursor.close()
            conexion.close()

    return render_template("login.html")


# Panel principal, disponible solo para usuarios autenticados

@app.route("/dashboard")
@requiere_login
def dashboard():
    total_empleos = 0

    if session["tipo_usuario"] == "empleador":
        conexion = conectar()
        cursor = conexion.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM empleos
            WHERE id_empleador = %s
        """, (session["id_usuario"],))

        total_empleos = cursor.fetchone()[0]

        cursor.close()
        conexion.close()

    return render_template(
        "dashboard.html",
        nombre=session["nombre"],
        tipo_usuario=session["tipo_usuario"],
        total_empleos=total_empleos
    )

@app.route("/mis-datos-contacto", methods=["GET", "POST"])
@requiere_login
def mis_datos_contacto():

    if session.get("tipo_usuario") not in ("habitante", "empleador"):
        flash("No tienes permiso para acceder.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)
        id_usuario = session["id_usuario"]

        if request.method == "POST":
            telefono = request.form.get("telefono", "").strip()
            correo = request.form.get("correo", "").strip()
            compartir = 1 if request.form.get("compartir_contacto") == "1" else 0

            if telefono and (
                not telefono.isdigit() or
                len(telefono) < 7 or
                len(telefono) > 15
            ):
                flash("Ingresa un teléfono válido, solo números.")
                return redirect(url_for("mis_datos_contacto"))

            if not correo or "@" not in correo or len(correo) > 254:
                flash("Ingresa un correo electrónico válido.")
                return redirect(url_for("mis_datos_contacto"))

            cursor.execute("""
                UPDATE usuarios
                SET telefono = %s,
                    correo = %s,
                    compartir_contacto = %s
                WHERE id_usuario = %s
            """, (telefono or None, correo, compartir, id_usuario))

            conexion.commit()

            flash("Tus datos de contacto se actualizaron correctamente.")
            return redirect(url_for("mis_datos_contacto"))

        cursor.execute("""
            SELECT nombre, telefono, correo, compartir_contacto
            FROM usuarios
            WHERE id_usuario = %s
        """, (id_usuario,))

        usuario = cursor.fetchone()

        if usuario is None:
            flash("No se encontró tu usuario.")
            return redirect(url_for("dashboard"))

        return render_template(
            "mis_datos_contacto.html",
            usuario=usuario
        )

    except Exception as e:
        conexion.rollback()
        print("Error al actualizar contacto:", e)
        flash("No se pudieron actualizar los datos.")
        return redirect(url_for("dashboard"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()


@app.route("/ver-hoja-vida/<int:id_empleo>/<int:id_usuario>")
@requiere_login
def ver_hoja_vida_postulante(id_empleo, id_usuario):

    if session.get("tipo_usuario") != "empleador":
        flash("Esta sección es solo para empleadores.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("mis_empleos"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        # Comprobar que el empleo pertenece al empleador
        # y que el habitante realmente se postuló.
        cursor.execute("""
            SELECT p.id_postulacion
            FROM postulaciones p
            INNER JOIN empleos e
                ON p.id_empleo = e.id_empleo
            WHERE p.id_empleo = %s
              AND p.id_usuario = %s
              AND e.id_empleador = %s
            LIMIT 1
        """, (
            id_empleo,
            id_usuario,
            session["id_usuario"]
        ))

        postulacion = cursor.fetchone()

        if not postulacion:
            flash("No tienes permiso para consultar esta hoja de vida.")
            return redirect(url_for("mis_empleos"))

        # Consultar la hoja de vida del postulante
        cursor.execute("""
            SELECT
                u.nombre,
                u.ubicacion,
                h.perfil_profesional,
                h.nivel_educativo,
                h.estudios,
                h.experiencia_laboral,
                h.habilidades
            FROM hojas_vida h
            INNER JOIN usuarios u
                ON h.id_usuario = u.id_usuario
            WHERE h.id_usuario = %s
        """, (id_usuario,))

        hoja_vida = cursor.fetchone()

        if not hoja_vida:
            flash("Este postulante todavía no ha creado su hoja de vida.")
            return redirect(url_for(
                "ver_postulantes",
                id_empleo=id_empleo
            ))

        return render_template(
            "ver_hoja_vida_postulante.html",
            hoja_vida=hoja_vida,
            id_empleo=id_empleo
        )

    except Exception as e:
        print("Error al consultar hoja de vida:", e)
        flash("No se pudo consultar la hoja de vida.")
        return redirect(url_for("mis_empleos"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

@app.route("/mis-postulantes")
@requiere_login
def mis_postulantes():

    if session.get("tipo_usuario") != "empleador":
        flash("Esta sección es solo para empleadores.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                e.id_empleo,
                e.titulo,
                e.estado,
                COUNT(p.id_postulacion) AS total_postulantes
            FROM empleos e
            LEFT JOIN postulaciones p
                ON e.id_empleo = p.id_empleo
            WHERE e.id_empleador = %s
            GROUP BY e.id_empleo, e.titulo, e.estado
            ORDER BY e.id_empleo DESC
        """, (session["id_usuario"],))

        ofertas = cursor.fetchall()

        return render_template(
            "mis_postulantes.html",
            ofertas=ofertas
        )

    except Exception as e:
        print("Error en mis postulantes:", e)
        flash("No se pudieron consultar los postulantes.")
        return redirect(url_for("dashboard"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

@app.route("/postulantes/<int:id_empleo>")
@requiere_login
def ver_postulantes(id_empleo):

    if session.get("tipo_usuario") != "empleador":
        flash("Esta sección es solo para empleadores.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("mis_empleos"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        # Verificar que el empleo pertenece al empleador
        cursor.execute("""
            SELECT id_empleo, titulo
            FROM empleos
            WHERE id_empleo = %s
              AND id_empleador = %s
        """, (id_empleo, session["id_usuario"]))

        empleo = cursor.fetchone()

        if not empleo:
            flash("No puedes consultar esta oferta.")
            return redirect(url_for("mis_empleos"))

        # Consultar los postulantes
        cursor.execute("""
            SELECT
                p.id_postulacion,
                p.fecha_postulacion,
                p.estado,
                u.id_usuario,
                u.nombre,
                u.ubicacion,

                CASE
                    WHEN p.estado = 'aceptada'
                         AND u.compartir_contacto = 1
                    THEN u.telefono
                    ELSE NULL
                END AS telefono,

                CASE
                    WHEN p.estado = 'aceptada'
                         AND u.compartir_contacto = 1
                    THEN u.correo
                    ELSE NULL
                END AS correo

            FROM postulaciones p

            INNER JOIN usuarios u
                ON p.id_usuario = u.id_usuario

            WHERE p.id_empleo = %s

            ORDER BY p.fecha_postulacion DESC
        """, (id_empleo,))

        postulantes = cursor.fetchall()

        return render_template(
            "postulantes.html",
            empleo=empleo,
            postulantes=postulantes
        )

    except Exception as e:
        print("Error al consultar postulantes:", e)
        flash("No se pudieron cargar los postulantes.")
        return redirect(url_for("mis_empleos"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

@app.route(
    "/actualizar-postulacion/<int:id_empleo>/<int:id_postulacion>",
    methods=["POST"]
)
@requiere_login
def actualizar_postulacion(id_empleo, id_postulacion):
    if session["tipo_usuario"] != "empleador":
        flash("Solo los empleadores pueden gestionar postulaciones.")
        return redirect(url_for("dashboard"))

    nuevo_estado = request.form.get("estado")

    if nuevo_estado not in ("aceptada", "rechazada"):
        flash("El estado seleccionado no es válido.")
        return redirect(url_for(
            "ver_postulantes", id_empleo=id_empleo
        ))

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE postulaciones p
        INNER JOIN empleos e
            ON p.id_empleo = e.id_empleo
        SET p.estado = %s
        WHERE p.id_postulacion = %s
          AND p.id_empleo = %s
          AND e.id_empleador = %s
    """, (
        nuevo_estado,
        id_postulacion,
        id_empleo,
        session["id_usuario"]
    ))

    conexion.commit()
    actualizado = cursor.rowcount

    cursor.close()
    conexion.close()

    if actualizado:
        flash("El estado de la postulación se actualizó.")
    else:
        flash("No se encontró la postulación correspondiente.")

    return redirect(url_for(
        "ver_postulantes", id_empleo=id_empleo
    ))


# Ofertas de empleo disponibles
# Ofertas de empleo disponibles
@app.route("/empleos-disponibles")
@requiere_login
def empleos_disponibles():

    conexion = conectar()

    if conexion is None:
        flash("No se pudo conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                e.id_empleo,
                e.titulo,
                e.descripcion,
                e.categoria,
                e.ubicacion,
                e.salario,
                e.tipo_contrato,
                e.fecha_publicacion,
                u.nombre AS nombre_empleador
            FROM empleos e
            INNER JOIN usuarios u
                ON e.id_empleador = u.id_usuario
            WHERE e.estado = 'disponible'
            ORDER BY e.fecha_publicacion DESC
        """)

        empleos = cursor.fetchall()

        # Consultar los empleos a los que ya se postuló el habitante
        empleos_postulados = []

        if session.get("tipo_usuario") == "habitante":
            cursor.execute("""
                SELECT id_empleo
                FROM postulaciones
                WHERE id_usuario = %s
            """, (session["id_usuario"],))

            empleos_postulados = [
                fila["id_empleo"]
                for fila in cursor.fetchall()
            ]

    except Exception as e:
        print("Error al consultar empleos:", e)
        flash("No se pudieron cargar los empleos.")
        empleos = []
        empleos_postulados = []

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

    
    return render_template(
        "empleos_disponibles.html",
        empleos=empleos,
        empleos_postulados=empleos_postulados
    )



# POSTULARSE A UNA OFERTA DE EMPLEO
@app.route("/postularse/<int:id_empleo>", methods=["POST"])
@requiere_login
def postularse(id_empleo):

    if session["tipo_usuario"] != "habitante":
        flash("Solo los habitantes pueden postularse.")
        return redirect(url_for("empleos_disponibles"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("empleos_disponibles"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        # Verificar que el empleo esté disponible
        cursor.execute("""
            SELECT id_empleo
            FROM empleos
            WHERE id_empleo = %s
            AND estado = 'disponible'
        """, (id_empleo,))

        empleo = cursor.fetchone()

        if not empleo:
            flash("Este empleo ya no está disponible.")
            return redirect(url_for("empleos_disponibles"))

        # Comprobar si el usuario ya se postuló
        cursor.execute("""
            SELECT id_postulacion
            FROM postulaciones
            WHERE id_empleo = %s
            AND id_usuario = %s
        """, (id_empleo, session["id_usuario"]))

        postulacion = cursor.fetchone()

        if postulacion:
            flash("Ya te postulaste a este empleo.")
            return redirect(url_for("empleos_disponibles"))

        # Registrar la postulación
        cursor.execute("""
            INSERT INTO postulaciones
            (id_empleo, id_usuario)
            VALUES (%s, %s)
        """, (id_empleo, session["id_usuario"]))

        conexion.commit()

        flash("¡Te postulaste correctamente!")

    except Exception as e:
        conexion.rollback()
        print("Error al postularse:", e)
        flash("No se pudo completar la postulación.")

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

    return redirect(url_for("empleos_disponibles"))

# Publicar servicio o emprendimiento
@app.route("/publicar-servicio", methods=["GET", "POST"])
@requiere_login
def publicar_servicio():

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden publicar servicios.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        if request.method == "POST":

            nombre = request.form.get("nombre", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            ubicacion = request.form.get("ubicacion", "").strip()
            categoria = request.form.get("id_categoria", "").strip()
            precio_texto = request.form.get("precio", "").strip()

            # Obtener el número de WhatsApp
            telefono_contacto = request.form.get(
                "telefono_contacto", ""
            ).strip()

            # Validar número de WhatsApp
            if telefono_contacto and (
                len(telefono_contacto) != 12
                or not telefono_contacto.startswith("57")
                or not telefono_contacto.isdigit()
            ):
                flash("Escribe un número de WhatsApp colombiano válido.")
                return redirect(url_for("publicar_servicio"))

            # Validar campos obligatorios
            if not nombre or not descripcion or not ubicacion:
                flash("Completa todos los campos obligatorios.")
                return redirect(url_for("publicar_servicio"))

            # Validar longitud de los campos
            if (
                len(nombre) > 150
                or len(ubicacion) > 150
                or len(descripcion) > 5000
            ):
                flash("Uno de los campos supera la longitud permitida.")
                return redirect(url_for("publicar_servicio"))

            # Validar categoría y precio
            try:
                id_categoria = int(categoria)

                precio = (
                    int(precio_texto)
                    if precio_texto
                    else None
                )

                if precio is not None and precio < 0:
                    raise ValueError

            except ValueError:
                flash("Selecciona una categoría y escribe un precio válido.")
                return redirect(url_for("publicar_servicio"))

            # Obtener el nombre de la categoría
            cursor.execute("""
                SELECT nombre
                FROM categorias
                WHERE id_categoria = %s
            """, (id_categoria,))

            categoria_encontrada = cursor.fetchone()

            if not categoria_encontrada:
                flash("La categoría seleccionada no existe.")
                return redirect(url_for("publicar_servicio"))

            nombre_categoria = categoria_encontrada["nombre"]

            # Guardar servicio con número de WhatsApp
            cursor.execute("""
                INSERT INTO servicios
                (
                    id_usuario,
                    nombre_servicio,
                    descripcion,
                    categoria,
                    ubicacion,
                    precio,
                    telefono_contacto,
                    estado
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                session["id_usuario"],
                nombre,
                descripcion,
                nombre_categoria,
                ubicacion,
                precio,
                telefono_contacto or None,
                "disponible"
            ))

            conexion.commit()

            flash("¡Tu servicio o emprendimiento se publicó correctamente!")

            return redirect(url_for("servicios_disponibles"))

        # Cargar categorías para el formulario
        cursor.execute("""
            SELECT id_categoria, nombre
            FROM categorias
            ORDER BY nombre
        """)

        categorias = cursor.fetchall()

        return render_template(
            "publicar_servicio.html",
            categorias=categorias
        )

    except Exception as e:
        conexion.rollback()
        print("Error al publicar servicio:", e)
        flash("Ocurrió un error al publicar el servicio.")
        return redirect(url_for("dashboard"))

    finally:
        if cursor is not None:
            cursor.close()

        conexion.close()



# MIS POSTULACIONES DEL HABITANTE

@app.route("/mis-postulaciones")
@requiere_login
def mis_postulaciones():

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden consultar sus postulaciones.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                p.id_postulacion,
                p.fecha_postulacion,
                p.estado,
                e.titulo,
                e.descripcion,
                e.ubicacion,
                e.salario,
                e.tipo_contrato,
                u.nombre AS nombre_empleador,

                CASE
                    WHEN p.estado = 'aceptada'
                         AND u.compartir_contacto = 1
                    THEN u.telefono
                    ELSE NULL
                END AS telefono_empleador,

                CASE
                    WHEN p.estado = 'aceptada'
                         AND u.compartir_contacto = 1
                    THEN u.correo
                    ELSE NULL
                END AS correo_empleador

            FROM postulaciones p

            INNER JOIN empleos e
                ON p.id_empleo = e.id_empleo

            INNER JOIN usuarios u
                ON e.id_empleador = u.id_usuario

            WHERE p.id_usuario = %s

            ORDER BY p.fecha_postulacion DESC
        """, (session["id_usuario"],))

        postulaciones = cursor.fetchall()

    except Exception as e:
        print("Error al consultar postulaciones:", e)
        flash("No se pudieron cargar tus postulaciones.")
        postulaciones = []

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

    return render_template(
        "mis_postulaciones.html",
        postulaciones=postulaciones
    )

# ==========================================
# MODULO DE HOJA DE VIDA
# ==========================================

@app.route("/mi-hoja-de-vida", methods=["GET", "POST"])
@requiere_login
def mi_hoja_de_vida():

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden gestionar su hoja de vida.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("No se pudo conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = conexion.cursor(dictionary=True)

    try:
        id_usuario = session["id_usuario"]

        if request.method == "POST":

            perfil = request.form.get("perfil_profesional", "").strip()
            nivel = request.form.get("nivel_educativo", "").strip()
            estudios = request.form.get("estudios", "").strip()
            experiencia = request.form.get("experiencia_laboral", "").strip()
            habilidades = request.form.get("habilidades", "").strip()

            cursor.execute("""
                INSERT INTO hojas_vida (
                    id_usuario,
                    perfil_profesional,
                    nivel_educativo,
                    estudios,
                    experiencia_laboral,
                    habilidades
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    perfil_profesional = %s,
                    nivel_educativo = %s,
                    estudios = %s,
                    experiencia_laboral = %s,
                    habilidades = %s
            """, (
                id_usuario,
                perfil,
                nivel,
                estudios,
                experiencia,
                habilidades,
                perfil,
                nivel,
                estudios,
                experiencia,
                habilidades
            ))

            conexion.commit()

            flash("Tu hoja de vida se guardó correctamente.")
            return redirect(url_for("mi_hoja_de_vida"))

        cursor.execute("""
            SELECT *
            FROM hojas_vida
            WHERE id_usuario = %s
        """, (id_usuario,))

        hoja_vida = cursor.fetchone()

        return render_template(
            "mi_hoja_de_vida.html",
            hoja_vida=hoja_vida
        )

    except Exception as e:
        conexion.rollback()
        print("Error en hoja de vida:", e)
        flash("Ocurrió un error al gestionar la hoja de vida.")
        return redirect(url_for("dashboard"))

    finally:
        cursor.close()
        conexion.close()


# ==========================================
# GENERAR HOJA DE VIDA EN PDF
# ==========================================

@app.route("/descargar-hoja-vida")
@requiere_login
def descargar_hoja_vida():

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden descargar su hoja de vida.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("No se pudo conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = conexion.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                u.nombre,
                u.correo,
                u.telefono,
                u.ubicacion,
                h.perfil_profesional,
                h.nivel_educativo,
                h.estudios,
                h.experiencia_laboral,
                h.habilidades
            FROM hojas_vida h
            INNER JOIN usuarios u
                ON h.id_usuario = u.id_usuario
            WHERE h.id_usuario = %s
        """, (session["id_usuario"],))

        datos = cursor.fetchone()

    finally:
        cursor.close()
        conexion.close()

    if not datos:
        flash("Primero debes completar tu hoja de vida.")
        return redirect(url_for("mi_hoja_de_vida"))

    buffer = BytesIO()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=(21 * cm, 29.7 * cm),
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm
    )

    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name="NombreCV",
        fontName="Helvetica-Bold",
        fontSize=19,
        leading=24,
        textColor=HexColor("#26734d"),
        alignment=TA_CENTER,
        spaceAfter=12
    ))

    estilos.add(ParagraphStyle(
        name="SeccionCV",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=17,
        textColor=HexColor("#26734d"),
        spaceBefore=16,
        spaceAfter=7
    ))

    estilos.add(ParagraphStyle(
        name="TextoCV",
        fontName="Helvetica",
        fontSize=10,
        leading=16,
        spaceAfter=8
    ))

    contenido = []

    def texto_seguro(valor):
        return escape(str(valor or "No registrado"))

    def agregar_seccion(titulo, valor):
        contenido.append(Paragraph(titulo, estilos["SeccionCV"]))
        texto = texto_seguro(valor).replace("\n", "<br/>")
        contenido.append(Paragraph(texto, estilos["TextoCV"]))

    contenido.append(Paragraph(
        texto_seguro(datos["nombre"]),
        estilos["NombreCV"]
    ))

    contenido.append(Paragraph(
        "HOJA DE VIDA | CONECTA CORREDOR",
        estilos["TextoCV"]
    ))

    contenido.append(Spacer(1, 10))

    contenido.append(HRFlowable(
        width="100%",
        thickness=1.5,
        color=HexColor("#26734d")
    ))

    agregar_seccion(
        "INFORMACIÓN DE CONTACTO",
        "Correo: " + str(datos["correo"] or "") + "\n" +
        "Teléfono: " + str(datos["telefono"] or "") + "\n" +
        "Ubicación: " + str(datos["ubicacion"] or "")
    )

    agregar_seccion(
        "PERFIL PROFESIONAL",
        datos["perfil_profesional"]
    )

    agregar_seccion(
        "NIVEL EDUCATIVO",
        datos["nivel_educativo"]
    )

    agregar_seccion(
        "FORMACIÓN ACADÉMICA",
        datos["estudios"]
    )

    agregar_seccion(
        "EXPERIENCIA LABORAL",
        datos["experiencia_laboral"]
    )

    agregar_seccion(
        "HABILIDADES",
        datos["habilidades"]
    )

    documento.build(contenido)

    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="mi_hoja_de_vida.pdf",
        mimetype="application/pdf"
    )

# ==========================================
# MODULO DE SERVICIOS DE LA COMUNIDAD
# ==========================================


# Consultar todos los servicios y emprendimientos@app.route("/servicios-disponibles")
@app.route("/servicios-disponibles")
@requiere_login
def servicios_disponibles():

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id_servicio,
                nombre_servicio,
                descripcion,
                categoria,
                ubicacion,
                precio,
                telefono_contacto
            FROM servicios
            WHERE estado = 'disponible'
            ORDER BY fecha_publicacion DESC
        """)

        servicios = cursor.fetchall()

        return render_template(
            "servicios_disponibles.html",
            servicios=servicios
        )

    except Exception as e:
        print("Error al consultar servicios:", e)
        flash("No se pudieron cargar los servicios.")
        return redirect(url_for("dashboard"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()
# Consultar mis servicios y emprendimientos publicados
@app.route("/mis-servicios")
@requiere_login
def mis_servicios():

    if session.get("tipo_usuario") != "habitante":
        flash("Esta sección es solo para habitantes.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("dashboard"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                id_servicio,
                nombre_servicio,
                descripcion,
                categoria,
                ubicacion,
                precio,
                estado
            FROM servicios
            WHERE id_usuario = %s
            ORDER BY id_servicio DESC
        """, (session["id_usuario"],))

        servicios = cursor.fetchall()

        return render_template(
            "mis_servicios.html",
            servicios=servicios
        )

    except Exception as e:
        print("Error al consultar mis servicios:", e)
        flash("No se pudieron cargar tus servicios.")
        return redirect(url_for("dashboard"))

    finally:
        if cursor is not None:
            cursor.close()

        conexion.close()

# Consultar el detalle de un servicio
@app.route("/detalle-servicio/<int:id_servicio>")
@requiere_login
def detalle_servicio(id_servicio):

    conexion = conectar()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            s.id_servicio,
            s.nombre_servicio,
            s.descripcion,
            s.categoria,
            s.ubicacion,
            s.precio,
            COALESCE(s.telefono_contacto, u.telefono) AS telefono_contacto,
            u.nombre AS nombre_usuario
        FROM servicios s
        INNER JOIN usuarios u
            ON s.id_usuario = u.id_usuario
        WHERE s.id_servicio = %s
          AND s.estado = 'disponible'
    """, (id_servicio,))

    servicio = cursor.fetchone()

    cursor.close()
    conexion.close()

    if not servicio:
        flash("El servicio no existe o ya no está disponible.")
        return redirect(url_for("servicios_disponibles"))

    return render_template(
        "detalle_servicio.html",
        servicio=servicio
    )


# Editar un servicio publicado
# Editar un servicio o emprendimiento publicado
@app.route("/editar-servicio/<int:id_servicio>", methods=["GET", "POST"])
@requiere_login
def editar_servicio(id_servicio):

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden editar servicios.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("mis_servicios"))

    cursor = None

    try:
        cursor = conexion.cursor(dictionary=True)

        # Verificar que el servicio pertenece al usuario
        cursor.execute("""
            SELECT *
            FROM servicios
            WHERE id_servicio = %s
              AND id_usuario = %s
        """, (id_servicio, session["id_usuario"]))

        servicio = cursor.fetchone()

        if not servicio:
            flash("No puedes editar este servicio.")
            return redirect(url_for("mis_servicios"))

        if request.method == "POST":

            nombre = request.form.get("nombre", "").strip()
            descripcion = request.form.get("descripcion", "").strip()
            ubicacion = request.form.get("ubicacion", "").strip()
            categoria_texto = request.form.get("id_categoria", "").strip()
            precio_texto = request.form.get("precio", "").strip()

            # Validar campos obligatorios
            if not nombre or not descripcion or not ubicacion:
                flash("Completa todos los campos obligatorios.")
                return redirect(url_for(
                    "editar_servicio",
                    id_servicio=id_servicio
                ))

            # Validar longitud de los campos
            if (
                len(nombre) > 150
                or len(ubicacion) > 150
                or len(descripcion) > 5000
            ):
                flash("Uno de los campos supera el límite permitido.")
                return redirect(url_for(
                    "editar_servicio",
                    id_servicio=id_servicio
                ))

            # Validar categoría y precio
            try:
                id_categoria = int(categoria_texto)
                precio = int(precio_texto) if precio_texto else None

                if precio is not None and precio < 0:
                    raise ValueError

            except (ValueError, TypeError):
                flash("Selecciona una categoría y escribe un precio válido.")
                return redirect(url_for(
                    "editar_servicio",
                    id_servicio=id_servicio
                ))

            # Obtener el nombre de la categoría
            cursor.execute("""
                SELECT nombre
                FROM categorias
                WHERE id_categoria = %s
            """, (id_categoria,))

            categoria_encontrada = cursor.fetchone()

            if not categoria_encontrada:
                flash("La categoría seleccionada no existe.")
                return redirect(url_for(
                    "editar_servicio",
                    id_servicio=id_servicio
                ))

            nombre_categoria = categoria_encontrada["nombre"]

            # Actualizar las columnas reales de MySQL
            cursor.execute("""
                UPDATE servicios
                SET nombre_servicio = %s,
                    descripcion = %s,
                    categoria = %s,
                    ubicacion = %s,
                    precio = %s
                WHERE id_servicio = %s
                  AND id_usuario = %s
            """, (
                nombre,
                descripcion,
                nombre_categoria,
                ubicacion,
                precio,
                id_servicio,
                session["id_usuario"]
            ))

            conexion.commit()

            flash("El servicio se actualizó correctamente.")
            return redirect(url_for("mis_servicios"))

        # Cargar categorías para el formulario
        cursor.execute("""
            SELECT id_categoria, nombre
            FROM categorias
            ORDER BY nombre
        """)

        categorias = cursor.fetchall()

        return render_template(
            "editar_servicio.html",
            servicio=servicio,
            categorias=categorias
        )

    except Exception as e:
        conexion.rollback()
        print("Error al editar servicio:", e)
        flash("No se pudo consultar o actualizar el servicio.")
        return redirect(url_for("mis_servicios"))

    finally:
        if cursor is not None:
            cursor.close()
        conexion.close()

# Eliminar un servicio publicado
# Eliminar un servicio o emprendimiento
# Eliminar servicio o emprendimiento
@app.route("/eliminar-servicio/<int:id_servicio>", methods=["POST"])
@requiere_login
def eliminar_servicio(id_servicio):

    if session.get("tipo_usuario") != "habitante":
        flash("Solo los habitantes pueden eliminar servicios.")
        return redirect(url_for("dashboard"))

    conexion = conectar()

    if conexion is None:
        flash("Error al conectar con la base de datos.")
        return redirect(url_for("mis_servicios"))

    cursor = None

    try:
        cursor = conexion.cursor()

        # Eliminar únicamente servicios del usuario actual
        cursor.execute("""
            DELETE FROM servicios
            WHERE id_servicio = %s
              AND id_usuario = %s
        """, (
            id_servicio,
            session["id_usuario"]
        ))

        eliminado = cursor.rowcount

        conexion.commit()

        if eliminado > 0:
            flash("El servicio se eliminó correctamente.")
        else:
            flash("No se encontró el servicio o no tienes permiso.")

    except Exception as e:
        conexion.rollback()
        print("Error al eliminar servicio:", e)
        flash("No se pudo eliminar el servicio.")

    finally:
        if cursor is not None:
            cursor.close()

        conexion.close()

    return redirect(url_for("mis_servicios"))



@app.route("/cerrar-sesion")
def cerrar_sesion():
    session.clear()
    flash("Has cerrado sesión correctamente.")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)