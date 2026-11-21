"""Explicit source-rendering hook; preserve context and do not guess source RGB."""
import pymupdf
from PIL import Image
def render_source_crop(document,page_index,bbox,scale):
    if scale<=0:raise ValueError('SCALE_REQUIRED')
    pix=document[page_index].get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False)
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    crop=image.crop(tuple(round(v*scale) for v in bbox))
    return crop,dict(renderer='PyMuPDF '+pymupdf.VersionBind,scale=scale,color_space='csRGB',alpha=False,grid='whole-page then integer crop',source_page=page_index+1)
