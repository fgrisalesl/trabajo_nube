# 04 · Tienda virtual de la facultad
## 📖 El caso
La tienda de productos institucionales (polos, stickers, gorras) solo vende físicamente los jueves. Quieren una mini-tienda en línea con catálogo y carrito simple, que resista el pico del lanzamiento de cada colección y no pierda pedidos si un componente falla.
## 👥 Actores
Comprador · Administrador de la tienda (catálogo y pedidos) · Bodega (despacho)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como comprador, quiero ver el catálogo con fotos y precios, para comprar sin preguntar.
- **[HU-02]** Como comprador, quiero armar un carrito y enviar mi pedido, para recogerlo en la facultad.
- **[HU-03]** Como administrador, quiero gestionar productos y ver pedidos entrantes, para preparar despachos.
- **[HU-04]** Como bodega, quiero que ningún pedido se pierda aunque la web falle, para cumplir con el comprador.
## ☁️ Requisitos cloud
ECS Fargate · RDS · S3 + CloudFront (estáticos) · **CloudFormation completo**
## ⚠️ Restricciones
Front y back separados (2 contenedores mínimo) · datos sensibles solo en RDS encriptado · **presupuesto objetivo ≤ 20 USD/mes**
## ✅ Entregables clave
Flujo de compra completo · backup/restore de RDS demostrado · diagrama con zonas de disponibilidad
## 🚀 Reto extra
Cola SQS para pedidos y worker asíncrono.
