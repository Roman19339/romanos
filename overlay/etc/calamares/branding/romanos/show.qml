import QtQuick 2.0;
import calamares.slideshow 1.0;
Presentation {
  id: presentation
  function onActivate() { }
  function onLeave() { }
  Timer { interval: 8000; running: presentation.activatedInCalamares; repeat: true; onTriggered: presentation.goToNextSlide() }
  Slide { Rectangle { anchors.fill: parent; color: "#141110"
    Text { anchors.centerIn: parent; color: "#f3ece6"; font.pixelSize: 22; horizontalAlignment: Text.AlignHCenter
      text: "RomanOS\nCaja, inventario, recetas y facturas en un solo lugar." } } }
  Slide { Rectangle { anchors.fill: parent; color: "#141110"
    Text { anchors.centerIn: parent; color: "#f3ece6"; font.pixelSize: 22; horizontalAlignment: Text.AlignHCenter
      text: "Claude viene integrado.\nPresiona Super + Espacio y pregunta lo que necesites." } } }
  Slide { Rectangle { anchors.fill: parent; color: "#141110"
    Text { anchors.centerIn: parent; color: "#f3ece6"; font.pixelSize: 22; horizontalAlignment: Text.AlignHCenter
      text: "Respaldo automático cada noche\nen Documentos › Respaldos." } } }
}
